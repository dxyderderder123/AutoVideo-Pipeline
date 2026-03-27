import sys
import os
import json
import hashlib
import shutil
import wave
import torch
import time
import logging
import argparse
from pathlib import Path
import threading
from typing import Optional, Dict, List

# Add VibeVoice code to path
from config import (
    PROJECT_ROOT, LIMIT_SEGMENTS, TEMP_BASE_DIR,
    GPU_MEMORY_THRESHOLD, TTS_INFERENCE_STEPS_FAST, TTS_INFERENCE_STEPS_NORMAL
)
VIBEVOICE_CODE_PATH = PROJECT_ROOT / "tools" / "VibeVoice" / "code"
sys.path.append(str(VIBEVOICE_CODE_PATH))

try:
    from vibevoice.modular.modeling_vibevoice_inference import VibeVoiceForConditionalGenerationInference
    from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor
except ImportError as e:
    print(f"Error importing VibeVoice modules: {e}")
    print(f"sys.path: {sys.path}")
    sys.exit(1)

# Setup logging
_log_level = os.environ.get("SELF_MEDIA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _log_level, logging.INFO), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Use shared locking module
try:
    from utils_lock import acquire_lock, release_lock
except ImportError:
    import sys
    sys.path.append(str(Path(__file__).parent))
    from utils_lock import acquire_lock, release_lock

# 尝试导入硬件监控器
try:
    from utils_hardware import hardware_scheduler, GPUManager
    _hardware_monitor_available = True
except ImportError:
    _hardware_monitor_available = False
    logger.warning("硬件监控器不可用，使用基础GPU锁")

# TTS缓存
_tts_cache: Dict[str, Path] = {}

def _get_tts_cache_key(text: str, voice_path: str, steps: int) -> str:
    """生成TTS缓存键"""
    content = f"{text}:{voice_path}:{steps}"
    return hashlib.md5(content.encode()).hexdigest()[:16]

def _get_cached_tts(text: str, voice_path: str, steps: int) -> Optional[Path]:
    """获取缓存的TTS文件路径"""
    key = _get_tts_cache_key(text, voice_path, steps)
    cached_path = _tts_cache.get(key)
    if cached_path and cached_path.exists():
        return cached_path
    return None

def _set_cached_tts(text: str, voice_path: str, steps: int, output_path: Path):
    """缓存TTS结果"""
    key = _get_tts_cache_key(text, voice_path, steps)
    _tts_cache[key] = output_path

# GPU Lock Mechanism for Concurrency Control
class GpuLock:
    """
    Ensures only one process uses the GPU for TTS at a time.
    Uses atomic directory locking compatible with Windows.
    """
    def __init__(self):
        self.lock_path = TEMP_BASE_DIR / "gpu.lock"
        self._stop_event = threading.Event()
        self._heartbeat_thread = None

    def __enter__(self):
        logger.info(f"Requesting GPU lock (waiting for other TTS tasks to finish)...")
        # Infinite wait (or very long) because we MUST wait for GPU
        try:
            stale_threshold = max(30, int(os.environ.get("SELF_MEDIA_GPU_LOCK_STALE_SECONDS", "120")))
        except Exception:
            stale_threshold = 120
        while True:
            if acquire_lock(self.lock_path, timeout_seconds=10, stale_threshold=stale_threshold):
                logger.info("Acquired GPU lock. Starting TTS generation.")
                self._stop_event.clear()
                self._heartbeat_thread = threading.Thread(target=self._heartbeat, daemon=True)
                self._heartbeat_thread.start()
                return
            else:
                # acquire_lock waits internally, but if it returns False, we loop
                logger.info("GPU busy, waiting...")
                time.sleep(5)

    def _heartbeat(self):
        while not self._stop_event.is_set():
            try:
                if self.lock_path.exists():
                    os.utime(self.lock_path, None)
            except Exception:
                pass
            time.sleep(30)

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self._stop_event.set()
            release_lock(self.lock_path)
            logger.info("Released GPU lock.")
        except Exception as e:
            logger.warning(f"Failed to release GPU lock: {e}")

# Constants
MODEL_PATH = PROJECT_ROOT / "tools" / "VibeVoice" / "model"
USER_REF_VOICE = PROJECT_ROOT / "assets/voice/reference.wav"
if USER_REF_VOICE.exists():
    VOICE_PRESET_PATH = USER_REF_VOICE
    logger.info(f"Using user reference voice: {VOICE_PRESET_PATH}")
else:
    VOICE_PRESET_PATH = VIBEVOICE_CODE_PATH / "demo/voices/en-Carter_man.wav"
    logger.info(f"Using default voice: {VOICE_PRESET_PATH}")

def load_model(device):
    logger.info(f"Loading VibeVoice model from {MODEL_PATH}")
    
    if not MODEL_PATH.exists():
        logger.warning(f"Model not found at {MODEL_PATH}. Auto-downloading from Hugging Face...")
        try:
            from huggingface_hub import snapshot_download
            # 如果在国内网络受限，可在终端运行前设置环境变量：set HF_ENDPOINT=https://hf-mirror.com
            snapshot_download(repo_id="vibevoice/VibeVoice-1.5B", local_dir=str(MODEL_PATH))
            logger.info("VibeVoice model downloaded successfully.")
        except Exception as e:
            logger.error(f"Failed to auto-download model: {e}")
            raise FileNotFoundError(f"Please manually download vibevoice/VibeVoice-1.5B to {MODEL_PATH}")

    processor = VibeVoiceProcessor.from_pretrained(str(MODEL_PATH))

    if device == "cuda":
        # Use standard efficient configuration: float16 + sdpa
        load_dtype = torch.float16
        attn_impl = "sdpa"
        # 2026 Optimization: Enable CUDNN benchmark for potential speedup
        torch.backends.cudnn.benchmark = True
    else:
        load_dtype = torch.float32
        attn_impl = "eager"
    
    # Restore device detection logic
    # device = "cuda" if torch.cuda.is_available() else "cpu"

    logger.info(f"Using device: {device}, dtype: {load_dtype}, attn: {attn_impl}")

    try:
        model = VibeVoiceForConditionalGenerationInference.from_pretrained(
            str(MODEL_PATH),
            torch_dtype=load_dtype,
            device_map=device,
            attn_implementation=attn_impl,
        )
    except Exception as e:
        logger.warning(f"Failed to load with {attn_impl}, falling back to sdpa. Error: {e}")
        model = VibeVoiceForConditionalGenerationInference.from_pretrained(
            str(MODEL_PATH),
            torch_dtype=load_dtype,
            device_map=device,
            attn_implementation='sdpa'
        )
    
    model.eval()
    fast_mode = os.environ.get("SELF_MEDIA_FAST_MODE", "").strip() == "1"
    steps_env = os.environ.get("SELF_MEDIA_TTS_STEPS", "").strip()
    if steps_env:
        try:
            steps = int(steps_env)
        except Exception:
            steps = 6
    else:
        steps = 4 if fast_mode else 6
    steps = max(2, min(12, steps))
    model.set_ddpm_inference_steps(num_steps=steps)
    
    return model, processor, steps

def _wav_duration_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            if rate:
                return frames / float(rate)
    except Exception:
        return None
    return None



def generate_tts(analysis_file: Path, tts_output_dir: Path):
    logger.info(f"Starting TTS generation. Input: {analysis_file}")
    
    if not analysis_file.exists():
        logger.error(f"Analysis file not found: {analysis_file}")
        sys.exit(1)

    with open(analysis_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not tts_output_dir.exists():
        tts_output_dir.mkdir(parents=True, exist_ok=True)

    tts_device_env = os.environ.get("SELF_MEDIA_TTS_DEVICE", "").strip().lower()
    if tts_device_env in {"cpu", "cuda"}:
        device = tts_device_env
    else:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    
    segments = data.get("segments", [])
    
    if LIMIT_SEGMENTS:
        logger.info(f"LIMIT_SEGMENTS is set to {LIMIT_SEGMENTS}. Processing only first {LIMIT_SEGMENTS} segments.")
        segments = segments[:LIMIT_SEGMENTS]

    voice_path = str(VOICE_PRESET_PATH)
    if not os.path.exists(voice_path):
        logger.error(f"Voice preset not found: {voice_path}")
        return

    updated_segments = []

    fast_mode = os.environ.get("SELF_MEDIA_FAST_MODE", "").strip() == "1"
    steps_env = os.environ.get("SELF_MEDIA_TTS_STEPS", "").strip()
    if steps_env:
        try:
            planned_steps = int(steps_env)
        except Exception:
            planned_steps = 20
    else:
        planned_steps = 12 if fast_mode else 20
    planned_steps = max(8, min(50, planned_steps))

    # 检查哪些片段需要生成TTS (使用缓存)
    missing_for_gpu = []
    cached_count = 0
    
    for i, seg in enumerate(segments):
        seg_id = seg.get("id", i+1)
        text = (seg.get("text", "") or "").replace("\n", " ").strip()
        updated_segments.append(seg)
        if not text:
            continue

        output_path = tts_output_dir / f"{seg_id}.wav"
        
        # 检查缓存
        cached_path = _get_cached_tts(text, voice_path, planned_steps)
        if cached_path and cached_path.exists():
            # 使用缓存，直接复制
            try:
                shutil.copy2(cached_path, output_path)
                # 获取音频时长
                duration = _wav_duration_seconds(output_path)
                if duration:
                    seg["duration"] = duration
                    seg["audio_file"] = str(output_path)
                    cached_count += 1
                    logger.info(f"片段 {seg_id} 使用缓存TTS (时长: {duration:.2f}s)")
                    continue
            except Exception as e:
                logger.warning(f"缓存复制失败，重新生成: {e}")
        
        missing_for_gpu.append((seg_id, text, output_path, seg))
    
    if cached_count > 0:
        logger.info(f"使用了 {cached_count} 个缓存的TTS文件")
    
    if not missing_for_gpu:
        logger.info("所有TTS都已缓存，跳过生成")
        # 保存结果
        output_json_path = analysis_file.parent / "analysis_tts.json"
        data["segments"] = updated_segments
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"TTS生成完成(全部缓存). 数据保存至 {output_json_path}")
        return

    tts_sleep_env = os.environ.get("SELF_MEDIA_TTS_SLEEP_SECONDS", "").strip()
    try:
        tts_sleep_seconds = float(tts_sleep_env) if tts_sleep_env else 0.0
    except Exception:
        tts_sleep_seconds = 0.0

    def _generate_missing_batch(model, processor, steps_used: int):
        """
        优化的批量TTS生成
        
        改进:
        1. 批量处理减少GPU上下文切换
        2. 使用更大的batch size
        3. 减少CUDA缓存清理频率
        """
        # 获取批量大小配置
        batch_size = int(os.environ.get("SELF_MEDIA_TTS_BATCH_SIZE", "2"))
        
        total_segments = len(missing_for_gpu)
        processed = 0
        
        while processed < total_segments:
            # 获取当前批次
            batch = missing_for_gpu[processed:processed + batch_size]
            batch_ids = [item[0] for item in batch]
            
            logger.info(f"批量处理TTS: 片段 {batch_ids} (批次大小: {len(batch)})")
            
            # GPU显存检查
            if _hardware_monitor_available and device == "cuda":
                gpu_status = hardware_scheduler.gpu_manager.get_status()
                if gpu_status["usage_percent"] > GPU_MEMORY_THRESHOLD * 100:
                    logger.warning(f"GPU显存使用率 {gpu_status['usage_percent']:.1f}% 超过阈值，等待释放...")
                    if not hardware_scheduler.gpu_manager.wait_for_available(timeout=60):
                        logger.error("等待GPU资源超时")
                        processed += len(batch)
                        continue
            
            # 准备批量输入
            full_scripts = [f"Speaker 1: {text}" for _, text, _, _ in batch]
            voice_samples_list = [[voice_path] for _ in batch]
            
            try:
                # 批量处理
                inputs = processor(
                    text=full_scripts,
                    voice_samples=voice_samples_list,
                    padding=True,
                    return_tensors="pt",
                    return_attention_mask=True,
                )
                
                for k, v in inputs.items():
                    if torch.is_tensor(v):
                        inputs[k] = v.to(device)

                with torch.inference_mode():
                    outputs = model.generate(
                        **inputs,
                        max_new_tokens=None,
                        cfg_scale=1.5,
                        tokenizer=processor.tokenizer,
                        generation_config={'do_sample': False},
                        is_prefill=True,
                    )

                # 保存每个音频
                for i, (seg_id, text, output_path, seg) in enumerate(batch):
                    if outputs.speech_outputs and len(outputs.speech_outputs) > i and outputs.speech_outputs[i] is not None:
                        sample_rate = 24000
                        audio_tensor = outputs.speech_outputs[i]
                        audio_samples = audio_tensor.shape[-1]
                        duration = audio_samples / sample_rate

                        processor.save_audio(audio_tensor, output_path=str(output_path))

                        seg["duration"] = duration
                        seg["audio_file"] = str(output_path)
                        
                        # 缓存生成的TTS
                        _set_cached_tts(text, voice_path, steps_used, output_path)
                        
                        logger.info(f"Generated {seg_id}.wav (Duration: {duration:.2f}s)")
                    else:
                        logger.error(f"No audio output for segment {seg_id}")
                        
            except Exception as e:
                logger.error(f"批量TTS生成错误: {e}")
                import traceback
                traceback.print_exc()
                # 批量失败时回退到单个生成
                for seg_id, text, output_path, seg in batch:
                    _generate_single(model, processor, steps_used, seg_id, text, output_path, seg, voice_path, device, tts_sleep_seconds)
            finally:
                try:
                    del inputs
                    del outputs
                except Exception:
                    pass
                # 每2个批次清理一次CUDA缓存
                if device == "cuda" and (processed // batch_size) % 2 == 0:
                    try:
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
            
            processed += len(batch)
            
            if tts_sleep_seconds > 0:
                logger.info(f"Sleeping for {tts_sleep_seconds}s between batches...")
                time.sleep(tts_sleep_seconds)
    
    def _generate_single(model, processor, steps_used, seg_id, text, output_path, seg, voice_path, device, tts_sleep_seconds):
        """单个TTS生成（批量失败时的回退）"""
        logger.info(f"单个处理片段 {seg_id}: {text[:30]}...")
        full_script = f"Speaker 1: {text}"
        voice_samples = [voice_path]

        try:
            inputs = processor(
                text=[full_script],
                voice_samples=[voice_samples],
                padding=True,
                return_tensors="pt",
                return_attention_mask=True,
            )
            for k, v in inputs.items():
                if torch.is_tensor(v):
                    inputs[k] = v.to(device)

            with torch.inference_mode():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=None,
                    cfg_scale=1.5,
                    tokenizer=processor.tokenizer,
                    generation_config={'do_sample': False},
                    is_prefill=True,
                )

            if outputs.speech_outputs and outputs.speech_outputs[0] is not None:
                sample_rate = 24000
                audio_tensor = outputs.speech_outputs[0]
                audio_samples = audio_tensor.shape[-1]
                duration = audio_samples / sample_rate

                processor.save_audio(audio_tensor, output_path=str(output_path))

                seg["duration"] = duration
                seg["audio_file"] = str(output_path)
                _set_cached_tts(text, voice_path, steps_used, output_path)
                logger.info(f"Generated {seg_id}.wav (Duration: {duration:.2f}s)")
        except Exception as e:
            logger.error(f"Error generating TTS for segment {seg_id}: {e}")
        finally:
            try:
                del inputs, outputs
            except:
                pass
            if device == "cuda":
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass

    if missing_for_gpu and device == "cuda":
        with GpuLock():
            model, processor, steps_used = load_model(device)
            _generate_missing_batch(model, processor, steps_used)
    elif missing_for_gpu:
        model, processor, steps_used = load_model(device)
        _generate_missing_batch(model, processor, steps_used)

    # Save updated JSON (overwrite or new file? Let's overwrite or return)
    # Actually, we should probably update the main data structure.
    # But since we might be running this as a step, let's save a new file or update the existing one.
    # The pipeline flow suggests passing data along.
    # Let's save to a new file `analysis_with_tts.json` or just overwrite.
    # Overwriting `analysis.json` might be risky if we crash.
    # Let's save to `analysis_tts.json` in the same dir as `analysis_file`.
    
    output_json_path = analysis_file.parent / "analysis_tts.json"
    data["segments"] = updated_segments
    
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    logger.info(f"TTS generation complete. Updated data saved to {output_json_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_json", type=Path, help="Path to analysis.json")
    parser.add_argument("--output_dir", type=Path, help="Directory to save audio files")
    args = parser.parse_args()
    
    if args.input_json and args.output_dir:
        generate_tts(args.input_json, args.output_dir)
    else:
        # Default for testing
        # Assuming we have a test run
        pass
