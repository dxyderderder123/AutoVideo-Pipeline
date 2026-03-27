import json
import subprocess
import logging
import argparse
import sys
import shutil
import os
from pathlib import Path
import concurrent.futures
from typing import Optional, List
from config import (
    VIDEO_SPEED_FACTOR, VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS,
    VIDEO_BITRATE, AUDIO_BITRATE, NVENC_PRESET,
    END_NOTE_ENABLE, END_NOTE_DURATION, END_NOTE_TEXT,
    FONT_PATH, FONT_COLOR, PREVIEW_MODE, PREVIEW_WIDTH, PREVIEW_HEIGHT
)

# Setup logging
_log_level = os.environ.get("SELF_MEDIA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _log_level, logging.INFO), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 尝试导入硬件监控器
try:
    from utils_hardware import hardware_scheduler
    _hardware_monitor_available = True
except ImportError:
    _hardware_monitor_available = False
    logger.warning("硬件监控器不可用")

def merge_all(input_json: Path, output_dir: Path, filename: str = None):
    """
    Merge all segments into a final video using a single-pass FFmpeg filter complex.
    This avoids double-encoding and temporary segment files.
    """
    logger.info(f"Starting Single-Pass Merge. Input: {input_json}")
    
    if not input_json.exists():
        logger.error(f"Input file not found: {input_json}")
        sys.exit(1)

    with open(input_json, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    segments = data.get("segments", [])
    if not segments:
        logger.error("No segments found.")
        return

    # Prepare inputs and filter chains
    input_args = []
    filter_chains = []
    
    # Track stream indices: 
    # Each segment contributes 1 video input and 1 audio input (or nullsrc)
    # We loop video inputs: -stream_loop -1 -i video
    # Audio inputs: -i audio
    
    video_stream_labels = []
    audio_stream_labels = []
    
    # 0. Check for Subtitles
    temp_dir = input_json.parent
    subtitle_ass_path = temp_dir / "output" / "subtitles_zh.ass"
    if not subtitle_ass_path.exists():
        subtitle_ass_path = temp_dir / "subtitles_zh.ass"
    
    has_subtitles = subtitle_ass_path.exists()
    
    # 2026 Fix: Prepare environment for FFmpeg (Avoid Windows Path Escaping Issues)
    # Copy Font to output directory to use relative path
    local_font_name = "font.ttf"
    local_font_path = output_dir / local_font_name
    
    # Ensure FONT_PATH is a Path object
    global FONT_PATH
    if isinstance(FONT_PATH, str):
        FONT_PATH = Path(FONT_PATH)
        
    try:
        if FONT_PATH.exists():
            shutil.copy2(FONT_PATH, local_font_path)
            logger.info(f"Copied font to {local_font_path} for safe FFmpeg usage")
        else:
            logger.warning(f"Font not found at {FONT_PATH}, end note might fail")
    except Exception as e:
        logger.warning(f"Failed to copy font: {e}")

    # Ensure subtitle file is in output_dir (if it exists)
    if has_subtitles:
        # If subtitle is not in output_dir, copy it
        if subtitle_ass_path.parent.resolve() != output_dir.resolve():
            dest_sub = output_dir / subtitle_ass_path.name
            try:
                shutil.copy2(subtitle_ass_path, dest_sub)
                subtitle_ass_path = dest_sub
                logger.info(f"Copied subtitles to {dest_sub}")
            except Exception as e:
                logger.warning(f"Failed to copy subtitles: {e}")

    current_input_idx = 0

    placeholder_input_idx = None
    placeholder_image = None
    if filename:
        candidate = output_dir / f"{filename}_horizontal.jpg"
        if candidate.exists():
            placeholder_image = candidate
    if placeholder_image is None:
        try:
            any_cover = next(iter(output_dir.glob("*_horizontal.jpg")), None)
            if any_cover and any_cover.exists():
                placeholder_image = any_cover
        except Exception:
            placeholder_image = None

    if placeholder_image:
        input_args.extend(["-loop", "1", "-i", str(placeholder_image)])
        placeholder_input_idx = current_input_idx
        current_input_idx += 1
        logger.info(f"Using cover placeholder for missing videos: {placeholder_image.name}")
    
    for i, seg in enumerate(segments):
        video_path = seg.get("video_file")
        video_files = seg.get("video_files", [])
        if not video_files and video_path:
            video_files = [video_path]
            
        tts_path = seg.get("audio_file")
        duration = seg.get("duration", 5.0)
        
        # Robustness: Check if video files actually exist
        valid_video_files = [v for v in video_files if v and Path(v).exists()]
        has_video_file = len(valid_video_files) > 0
            
        # 2026 Fix: Trust the actual TTS audio duration over the estimated JSON duration
        # This prevents video looping or silence if the estimate was off.
        if tts_path and Path(tts_path).exists():
            audio_duration = None
            
            # 方法1: 尝试使用WAV文件头直接读取(更快)
            try:
                import wave
                with wave.open(str(tts_path), 'rb') as wav_file:
                    frames = wav_file.getnframes()
                    rate = wav_file.getframerate()
                    if rate > 0:
                        audio_duration = frames / float(rate)
                        logger.debug(f"WAV duration from header: {audio_duration:.3f}s")
            except Exception as wav_e:
                logger.debug(f"WAV header read failed: {wav_e}")
            
            # 方法2: 如果方法1失败，使用ffprobe
            if audio_duration is None:
                try:
                    cmd = [
                        "ffprobe", 
                        "-v", "error", 
                        "-show_entries", "format=duration", 
                        "-of", "default=noprint_wrappers=1:nokey=1", 
                        str(tts_path)
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                    audio_duration = float(result.stdout.strip())
                except Exception as e:
                    logger.warning(f"Failed to probe audio duration for {tts_path}: {e}. Using estimated duration.")
                    audio_duration = None
            
            # 更新时长
            if audio_duration is not None and abs(audio_duration - duration) > 0.1:
                logger.info(f"Correcting duration for segment {seg.get('id')}: {duration:.2f}s -> {audio_duration:.2f}s (based on TTS)")
                duration = audio_duration

        video_indices = []
        if has_video_file:
            # Input Video(s) (Looped)
            for v_path in valid_video_files:
                input_args.extend(["-stream_loop", "-1", "-i", v_path])
                video_indices.append(current_input_idx)
                current_input_idx += 1
        else:
            logger.warning(f"Segment {seg.get('id')} missing video files. Using placeholder.")
            # No input added here, will handle in filter
        
        # Input Audio (TTS or Silence)
        if tts_path and Path(tts_path).exists():
            input_args.extend(["-i", tts_path])
            audio_idx = current_input_idx
            current_input_idx += 1
            has_audio_file = True
        else:
            # If no audio file, we don't add an input, we generate silence in filter
            has_audio_file = False
            
        # 1. Video Filter Chain for Segment i
        # Scale -> Crop -> FPS -> Trim
        v_label = f"v{i}"
        
        if has_video_file:
            num_vids = len(valid_video_files)
            if num_vids == 1:
                filter_chains.append(
                    f"[{video_indices[0]}:v]setpts=PTS/{VIDEO_SPEED_FACTOR},"
                    f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
                    f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
                    f"fps={VIDEO_FPS},"
                    f"trim=duration={duration},"
                    f"setpts=PTS-STARTPTS[{v_label}]"
                )
            else:
                sub_dur = duration / num_vids
                v_sub_labels = []
                for j, v_idx in enumerate(video_indices):
                    sub_label = f"v{i}_s{j}"
                    filter_chains.append(
                        f"[{v_idx}:v]setpts=PTS/{VIDEO_SPEED_FACTOR},"
                        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
                        f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
                        f"fps={VIDEO_FPS},"
                        f"trim=duration={sub_dur},"
                        f"setpts=PTS-STARTPTS[{sub_label}]"
                    )
                    v_sub_labels.append(f"[{sub_label}]")
                
                concat_inputs = "".join(v_sub_labels)
                filter_chains.append(f"{concat_inputs}concat=n={num_vids}:v=1:a=0[{v_label}]")
        else:
            if placeholder_input_idx is not None:
                filter_chains.append(
                    f"[{placeholder_input_idx}:v]"
                    f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
                    f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
                    f"fps={VIDEO_FPS},"
                    f"setsar=1,"
                    f"trim=duration={duration},"
                    f"setpts=PTS-STARTPTS[{v_label}]"
                )
            else:
                filter_chains.append(
                    f"color=c=black:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d={duration}:r={VIDEO_FPS},"
                    f"setsar=1,"
                    f"trim=duration={duration},"
                    f"setpts=PTS-STARTPTS[{v_label}]"
                )
            
        video_stream_labels.append(f"[{v_label}]")
        
        # 2. Audio Filter Chain for Segment i
        a_label = f"a{i}"
        if has_audio_file:
            # apad ensures we don't run out of audio if video is slightly longer
            # atrim cuts it exactly to duration
            filter_chains.append(
                f"[{audio_idx}:a]volume=1.0,apad,atrim=0:{duration},asetpts=PTS-STARTPTS[{a_label}]"
            )
        else:
            # Generate silence
            filter_chains.append(
                f"anullsrc=r=44100:cl=stereo:d={duration}[{a_label}]"
            )
        audio_stream_labels.append(f"[{a_label}]")

    # Handle End Note (Optional)
    # We will treat it as one extra segment if enabled
    if END_NOTE_ENABLE and filename:
        end_note_duration = END_NOTE_DURATION
        # Generate a black video with text using filter complex is possible but verbose.
        # Simpler: Generate a temporary end_note.mp4 and add it as input.
        # But to keep "single pass" philosophy, let's use color source + drawtext.
        
        # FIX: Do not replace newline with \N here. We will use textfile option in create_end_note_video
        # to correctly handle newlines and special characters.
        end_note_content = END_NOTE_TEXT.strip().replace("{filename}", filename)
        
        # Alternative: Render end note to a temp file once, then treat as input.
        # This is safer/easier than dynamic drawtext in a huge graph.
        end_note_temp = output_dir / "temp_end_note.mp4"
        # Use relative paths by running in output_dir
        create_end_note_video(end_note_temp, end_note_content, end_note_duration, cwd=output_dir, font_name=local_font_name)
        
        if end_note_temp.exists():
            input_args.extend(["-stream_loop", "-1", "-i", str(end_note_temp)])
            en_vid_idx = current_input_idx
            
            # End Note Video Filter
            v_en_label = "v_end"
            filter_chains.append(
                f"[{en_vid_idx}:v]setpts=PTS/{VIDEO_SPEED_FACTOR},"
                f"scale=1920:1080:force_original_aspect_ratio=increase,"
                f"crop=1920:1080,fps={VIDEO_FPS},trim=duration={end_note_duration},"
                f"setpts=PTS-STARTPTS[{v_en_label}]"
            )
            video_stream_labels.append(f"[{v_en_label}]")
            
            # End Note Audio (Silence)
            a_en_label = "a_end"
            filter_chains.append(
                f"anullsrc=r=44100:cl=stereo:d={end_note_duration}[{a_en_label}]"
            )
            audio_stream_labels.append(f"[{a_en_label}]")
            
            current_input_idx += 1

    # 3. Concat Everything
    n_segments = len(video_stream_labels)
 # Prepare Concat Inputs (Must be [v0][a0][v1][a1]... for concat=n=...:v=1:a=1)
    concat_inputs = []
    for v_label, a_label in zip(video_stream_labels, audio_stream_labels):
        concat_inputs.append(f"{v_label}{a_label}")
    
    concat_str = "".join(concat_inputs)

    filter_chains.append(
        f"{concat_str}concat=n={n_segments}:v=1:a=1[v_concat][a_concat]"
    )
    
    # 4. Post-Processing
    # Audio Loudness
    filter_chains.append(
        f"[a_concat]loudnorm=I=-14:TP=-1.0:LRA=11[a_final]"
    )
    
    # Subtitles
    if has_subtitles:
        # Use relative path for subtitles (Safe because we set cwd=output_dir)
        subtitle_filename = subtitle_ass_path.name
        filter_chains.append(
            f"[v_concat]subtitles='{subtitle_filename}'[v_final]"
        )
        map_v = "[v_final]"
    else:
        map_v = "[v_concat]"
        
    map_a = "[a_final]"

    # 5. Write Filter Script
    filter_script_content = ";\n".join(filter_chains)
    filter_script_path = output_dir / "filter_complex_script.txt"
    with open(filter_script_path, "w", encoding="utf-8") as f:
        f.write(filter_script_content)

    # 6. Execute FFmpeg
    final_output = output_dir / "final_video.mp4"
    logger.info(f"Rendering final video to {final_output} (Single Pass)...")
    
    # Construct FFmpeg command with optimized parameters
    cmd = [
        "ffmpeg", "-y",
        "-hide_banner", "-loglevel", "error", # Reduce log noise
    ]
    
    # Add input arguments
    cmd.extend(input_args)
    
    cmd.extend([
        "-filter_complex_script", str(filter_script_path),
        "-map", "[v_final]" if has_subtitles else "[v_concat]", 
        "-map", "[a_final]",
        "-c:v", "h264_nvenc",      # NVIDIA GPU Encoder
        "-preset", NVENC_PRESET,   # Use configured preset (e.g., p4)
        "-rc", "vbr",              # Variable Bitrate
        "-cq", "23",               # Constant Quality (good balance)
        "-b:v", VIDEO_BITRATE,     # Target Bitrate from config
        "-maxrate", "20M",         # Max bitrate constraint
        "-bufsize", "40M",         # Buffer size for bitrate control
        "-pix_fmt", "yuv420p",     # Standard compatibility
        "-c:a", "aac", 
        "-b:a", AUDIO_BITRATE,     # Audio Bitrate from config
        str(final_output)
    ])
    
    try:
        # Check ffmpeg existence first (fail fast)
        # subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        # Run command
        logger.info(f"Executing FFmpeg with {len(input_args)//2} inputs...")
        # 2026 Fix: Run in output_dir so relative paths in filter_complex (like subtitles) work correctly
        subprocess.run(cmd, check=True, cwd=output_dir)
        logger.info("Merge complete!")
        
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg Merge failed: {e}")
        # Debug: Print filter script snippet
        logger.error(f"Filter Script (first 500 chars):\n{filter_script_content[:500]}...")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

def create_end_note_video(output_path, text, duration, cwd=None, font_name=None):
    """
    Helper to generate a simple black video with centered text.
    Uses a temporary text file to handle special characters and newlines correctly.
    Supports relative paths via cwd to avoid FFmpeg escaping issues.
    """
    if output_path.exists():
        return
        
    # Write text to a temporary file
    # Use utf-8 encoding for Chinese characters
    text_file = output_path.with_suffix('.txt')
    try:
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(text)
    except Exception as e:
        logger.error(f"Failed to write end note text file: {e}")
        return

    # Prepare paths for drawtext
    if cwd and font_name:
        # Use relative paths
        font_file = font_name
        # Resolve text_file relative to cwd if possible
        try:
            # If text_file is absolute, try to make it relative to cwd
            if text_file.is_absolute():
                text_file_rel = text_file.relative_to(cwd)
                text_file_path = str(text_file_rel).replace("\\", "/").replace(":", "\\:")
            else:
                # If it's already relative (unlikely given Path usage but possible), use as is
                text_file_path = str(text_file).replace("\\", "/").replace(":", "\\:")
        except ValueError:
            # Fallback to absolute if not in cwd
            text_file_path = str(text_file).replace("\\", "/").replace(":", "\\:")
    else:
        # Use absolute paths with escaping
        font_file = str(FONT_PATH).replace("\\", "/").replace(":", "\\:")
        text_file_path = str(text_file).replace("\\", "/").replace(":", "\\:")
    
    # Reduced fontsize from 60 to 50 to prevent overflow
    # Use config NVENC_PRESET here too for consistency
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=black:s=1920x1080:d={duration}",
        "-vf", f"drawtext=fontfile='{font_file}':textfile='{text_file_path}':fontcolor={FONT_COLOR}:fontsize=50:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v", "h264_nvenc", "-preset", NVENC_PRESET,
        "-pix_fmt", "yuv420p",
        str(output_path)
    ]
    
    try:
        # Pass cwd to subprocess if provided
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=cwd)
    except Exception as e:
        logger.warning(f"Failed to create end note video: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_json", type=Path, help="Path to analysis_sfx.json")
    parser.add_argument("--output_dir", type=Path, help="Directory to save output videos")
    parser.add_argument("--filename", type=str, help="Original filename for End Note (optional)")
    args = parser.parse_args()
    
    if args.input_json and args.output_dir:
        merge_all(args.input_json, args.output_dir, args.filename)
