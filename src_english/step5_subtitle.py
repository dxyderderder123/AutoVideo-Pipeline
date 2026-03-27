import argparse
import json
import os
import sys
import subprocess
import logging
import hashlib
from pathlib import Path
from typing import Optional, Dict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 尝试导入硬件监控器
try:
    from utils_hardware import hardware_scheduler
    _hardware_monitor_available = True
except ImportError:
    _hardware_monitor_available = False
    logger.warning("硬件监控器不可用")

# 字幕缓存
_subtitle_cache: Dict[str, Path] = {}

def _get_subtitle_cache_key(audio_hash: str) -> str:
    """生成字幕缓存键"""
    return hashlib.md5(audio_hash.encode()).hexdigest()[:16]

def _get_cached_subtitle(audio_hash: str) -> Optional[Path]:
    """获取缓存的字幕文件路径"""
    key = _get_subtitle_cache_key(audio_hash)
    cached_path = _subtitle_cache.get(key)
    if cached_path and cached_path.exists():
        return cached_path
    return None

def _set_cached_subtitle(audio_hash: str, output_path: Path):
    """缓存字幕结果"""
    key = _get_subtitle_cache_key(audio_hash)
    _subtitle_cache[key] = output_path

def generate_simple_srt(analysis_path, output_srt):
    """
    Fallback SRT generation when WhisperX is unavailable.
    每个 TTS 段生成一条字幕，时间从 WAV 文件实际时长累加。
    短句显示由 step6 ASS 渲染层处理。
    """
    logger.warning("WhisperX unavailable, using segment-level SRT generation.")
    
    try:
        with open(analysis_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        segments = data.get("segments", [])
        tts_dir = analysis_path.parent / "tts"
        
        srt_content = ""
        index = 1
        current_time = 0.0
        
        for seg in segments:
            text = seg.get("text", "").strip()
            if not text:
                continue
                
            seg_id = seg.get("id")
            actual_duration = seg.get("duration", 5.0)
            
            # 从 WAV 获取准确时长（与 step7 使用相同方式）
            if tts_dir.exists():
                wav_path = tts_dir / f"{seg_id}.wav"
                if wav_path.exists():
                    try:
                        import wave
                        with wave.open(str(wav_path), 'rb') as wav_file:
                            frames = wav_file.getnframes()
                            rate = wav_file.getframerate()
                            if rate > 0:
                                actual_duration = frames / float(rate)
                    except Exception:
                        pass
            
            def fmt(s):
                hours = int(s // 3600)
                minutes = int((s % 3600) // 60)
                seconds = int(s % 60)
                millis = int((s * 1000) % 1000)
                return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

            start_time = current_time
            end_time = current_time + actual_duration
            current_time = end_time
            
            # 2026 Fix: Fallback Subtitle Splitting
            # 将 20 秒的大段字幕，切分为 12 词左右的短句循序渐进显示。
            # 之前导致时间累积漂移的元凶（step6 的 MIN_GAP=500ms）已被彻底删除，这里安全的字数等比推算可以满足视觉节奏需求！
            words = text.split()
            MAX_WORDS = 12
            if len(words) <= MAX_WORDS:
                srt_content += f"{index}\n{fmt(start_time)} --> {fmt(end_time)}\n{text}\n\n"
                index += 1
            else:
                chunks = []
                current_chunk = []
                # 在标点处寻找最佳切分点
                for word in words:
                    current_chunk.append(word)
                    if len(current_chunk) >= MAX_WORDS or (len(current_chunk) > 5 and word[-1] in '.?!;,'):
                        chunks.append(' '.join(current_chunk))
                        current_chunk = []
                if current_chunk:
                    chunks.append(' '.join(current_chunk))
                    
                total_chars = sum(len(c) for c in chunks)
                chunk_start = start_time
                for chunk in chunks:
                    chunk_ratio = len(chunk) / max(total_chars, 1)
                    chunk_dur = actual_duration * chunk_ratio
                    chunk_end = chunk_start + chunk_dur
                    srt_content += f"{index}\n{fmt(chunk_start)} --> {fmt(chunk_end)}\n{chunk}\n\n"
                    index += 1
                    chunk_start = chunk_end
                
        with open(output_srt, 'w', encoding='utf-8') as f:
            f.write(srt_content)
            
        logger.info(f"Segment-level SRT generated: {output_srt} ({index - 1} lines)")
        return True
        
    except Exception as e:
        logger.error(f"SRT generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    parser = argparse.ArgumentParser(description="Subtitle Generation Step (Wrapper for WhisperX)")
    parser.add_argument("--dir", required=True, help="Project directory containing analysis.json")
    args = parser.parse_args()
    
    project_dir = Path(args.dir)
    
    # Priority: analysis_video.json > analysis.json
    # Removed analysis_sfx.json and analysis_tts.json logic to simplify
    # Actually, step3_video.py generates analysis_video.json, which contains everything.
    # step2_tts.py generates analysis_tts.json
    # workflow now passes analysis_video.json as final input to step 7, so we should look for that or tts.
    
    # Let's check for analysis_merged.json first (created by workflow)
    if (project_dir / "analysis_merged.json").exists():
        analysis_path = project_dir / "analysis_merged.json"
    elif (project_dir / "analysis_video.json").exists():
        analysis_path = project_dir / "analysis_video.json"
    elif (project_dir / "analysis_tts.json").exists():
        analysis_path = project_dir / "analysis_tts.json"
    else:
        analysis_path = project_dir / "analysis.json"
        
    logger.info(f"Using analysis file: {analysis_path}")
    
    tts_dir = project_dir / "tts"
    output_dir = project_dir / "output"
    output_srt = output_dir / "subtitles.srt"
    
    # Define path to WhisperX tool
    # step5_subtitle.py is in v:\Default\Desktop\Self-media\src_english
    # Tools are in v:\Default\Desktop\Self-media\tools
    current_dir = Path(__file__).parent.absolute()
    # Go up one level: src_english -> Self-media
    project_root = current_dir.parent
    
    whisperx_script = project_root / "tools" / "WhisperX" / "align.py"
    models_dir = project_root / "tools" / "WhisperX" / "models"
    
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Clean up redundant files (as per user request)
    redundant_files = [
        output_dir / "subtitles.ass",
        output_dir / "subtitles_zh.ass"
    ]
    for f in redundant_files:
        if f.exists():
            try:
                os.remove(f)
                logger.info(f"Removed redundant file: {f}")
            except Exception as e:
                logger.warning(f"Failed to remove {f}: {e}")

    if not analysis_path.exists():
        logger.error(f"Analysis file not found: {analysis_path}")
        sys.exit(1)
        
    if not tts_dir.exists():
        logger.error(f"TTS directory not found: {tts_dir}")
        sys.exit(1)
        
    if os.environ.get("SELF_MEDIA_DISABLE_WHISPERX", "").strip() == "1":
        logger.info("WhisperX alignment disabled by SELF_MEDIA_DISABLE_WHISPERX=1. Using fallback SRT.")
        if generate_simple_srt(analysis_path, output_srt):
            logger.info("Fallback successful.")
            return
        logger.error("Fallback failed. No subtitles generated.")
        sys.exit(1)

    logger.info(f"Invoking WhisperX Alignment Tool: {whisperx_script}")
    
    # Construct command
    # Use the same python interpreter
    cmd = [
        sys.executable,
        str(whisperx_script),
        "--analysis", str(analysis_path),
        "--tts_dir", str(tts_dir),
        "--output", str(output_srt),
        "--models_dir", str(models_dir)
    ]
    
    try:
        # Check if whisperx is installed before running subprocess to avoid ugly traceback
        try:
            import whisperx
        except ImportError:
            logger.warning("WhisperX module not found in current environment. Skipping alignment.")
            raise subprocess.CalledProcessError(1, cmd) # Trigger fallback

        result = subprocess.run(cmd, check=True, capture_output=False)
        logger.info("Subtitle generation completed successfully via WhisperX.")
    except (subprocess.CalledProcessError, ImportError) as e:
        logger.warning(f"WhisperX alignment failed or missing: {e}")
        logger.info("Attempting fallback to Simple SRT Generation...")
        
        if generate_simple_srt(analysis_path, output_srt):
            logger.info("Fallback successful.")
        else:
            logger.error("Fallback failed. No subtitles generated.")
            sys.exit(1)

if __name__ == "__main__":
    main()
