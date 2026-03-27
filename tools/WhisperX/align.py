import argparse
import json
import os
import sys
import torch
import torchaudio
import whisperx
import logging
from pathlib import Path
import subprocess
import tempfile

try:
    import nltk
    nltk.data.find('tokenizers/punkt')
except LookupError:
    import nltk
    nltk.download('punkt', quiet=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def format_timestamp(seconds: float) -> str:
    millis = int((seconds % 1) * 1000)
    seconds = int(seconds)
    minutes = seconds // 60
    hours = minutes // 60
    minutes = minutes % 60
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

def concatenate_audio_files(tts_dir, segment_ids, output_path):
    """将多个音频文件合并为一个文件"""
    audio_files = []
    for seg_id in segment_ids:
        audio_path = os.path.join(tts_dir, f"{seg_id}.wav")
        if os.path.exists(audio_path):
            audio_files.append(audio_path)
    
    if not audio_files:
        return None, []
    
    # 使用ffmpeg合并音频
    # 创建文件列表
    list_file = output_path + ".list.txt"
    with open(list_file, 'w', encoding='utf-8') as f:
        for af in audio_files:
            f.write(f"file '{af}'\n")
    
    # 合并
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output_path
    ]
    
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        os.remove(list_file)
        return output_path, audio_files
    except Exception as e:
        logger.error(f"Failed to concatenate audio: {e}")
        if os.path.exists(list_file):
            os.remove(list_file)
        return None, []

def get_audio_duration(audio_path):
    """获取音频时长"""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", 
           "-of", "default=noprint_wrappers=1:nokey=1", audio_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())

def align_segments(analysis_path, tts_dir, output_srt, models_dir):
    os.environ["HF_HOME"] = models_dir
    os.environ["TORCH_HOME"] = models_dir
    
    device_env = os.environ.get("SELF_MEDIA_WHISPERX_DEVICE", "").strip().lower()
    if device_env in {"cpu", "cuda"}:
        device = device_env
    else:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Using device: {device}")
    
    with open(analysis_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 获取所有segment
    segments = data.get('segments', [])
    if not segments:
        logger.error("No segments found in analysis file")
        sys.exit(1)
    
    segment_ids = [s['id'] for s in segments]
    segment_texts = [s['text'] for s in segments]
    full_text = " ".join(segment_texts)
    
    # 合并所有音频文件
    logger.info("Concatenating audio files...")
    temp_audio = os.path.join(os.path.dirname(output_srt), "temp_combined.wav")
    combined_audio, audio_files = concatenate_audio_files(tts_dir, segment_ids, temp_audio)
    
    if not combined_audio:
        logger.error("Failed to create combined audio file")
        sys.exit(1)
    
    # 获取每个segment的音频时长，用于后续分割
    segment_durations = []
    for af in audio_files:
        duration = get_audio_duration(af)
        segment_durations.append(duration)
    
    logger.info(f"Combined audio duration: {sum(segment_durations):.2f}s")
    
    # 加载对齐模型
    logger.info("Loading WhisperX Alignment Model...")
    try:
        model, metadata = whisperx.load_align_model(language_code="en", device=device)
    except Exception as e:
        logger.error(f"Failed to load alignment model: {e}")
        if os.path.exists(temp_audio):
            os.remove(temp_audio)
        sys.exit(1)
    
    # 加载合并后的音频
    logger.info("Loading combined audio...")
    audio = whisperx.load_audio(combined_audio)
    
    # 创建完整的transcript对象
    # 我们需要把文本按segment分割，每个segment有自己的时间范围
    transcript = []
    current_offset = 0.0
    for i, (seg, duration) in enumerate(zip(segments, segment_durations)):
        transcript.append({
            "text": seg['text'],
            "start": current_offset,
            "end": current_offset + duration
        })
        current_offset += duration
    
    # 执行对齐
    logger.info("Performing forced alignment on combined audio...")
    try:
        result = whisperx.align(
            transcript,
            model,
            metadata,
            audio,
            device,
            return_char_alignments=False
        )
    except Exception as e:
        logger.error(f"Alignment failed: {e}")
        if os.path.exists(temp_audio):
            os.remove(temp_audio)
        sys.exit(1)
    
    # 处理对齐结果
    words = result.get('word_segments', [])
    
    if not words:
        logger.error("No words aligned")
        if os.path.exists(temp_audio):
            os.remove(temp_audio)
        sys.exit(1)
    
    # 智能分割成字幕行
    MIN_GAP = 0.05  # 50ms最小间隔（词级对齐已足够精确，不需要大间隔）
    SOFT_MAX_CHARS = 60   # 每条字幕约10-15个英语单词（短句）
    HARD_MAX_CHARS = 80   # 硬上限
    STRONG_BREAK = {'.', '?', '!', ';'}
    WEAK_BREAK = {',', '—', '-', '–', ':'}
    ALL_BREAK = STRONG_BREAK.union(WEAK_BREAK)
    ABBREVIATIONS = {
        'Dr.', 'Mr.', 'Mrs.', 'Ms.', 'Prof.', 'St.', 'vs.', 'etc.', 'e.g.', 'i.e.', 'Jr.', 'Sr.',
        'dr.', 'mr.', 'mrs.', 'ms.', 'prof.', 'st.', 'jr.', 'sr.', 'approx.', 'no.'
    }
    
    def clean_word_for_abbr(w):
        return w.strip().rstrip(',:;!?"\'"\'')
    
    all_lines = []
    global_index = 1
    current_line_words = []
    current_line_len = 0
    
    for i, w in enumerate(words):
        if 'start' not in w or 'end' not in w:
            w['start'] = 0.0
            w['end'] = 0.1
        
        raw_word = w['word'].strip()
        cw = clean_word_for_abbr(raw_word)
        word_len = len(raw_word) + 1
        
        # 强制分割（超过最大长度）
        if current_line_words and (current_line_len + word_len > HARD_MAX_CHARS):
            text_line = " ".join([x['word'] for x in current_line_words])
            start_time = current_line_words[0]['start']
            end_time = current_line_words[-1]['end']
            
            # 应用最小间隔
            if all_lines:
                prev_end = all_lines[-1]['end']
                if start_time - prev_end < MIN_GAP:
                    start_time = prev_end + MIN_GAP
            
            all_lines.append({
                "index": global_index,
                "start": start_time,
                "end": end_time,
                "text": text_line
            })
            global_index += 1
            current_line_words = []
            current_line_len = 0
        
        current_line_words.append(w)
        current_line_len += word_len
        
        # 标点分割
        if raw_word and raw_word[-1] in ALL_BREAK:
            if cw in ABBREVIATIONS:
                continue
            if raw_word.endswith(":") and len(current_line_words) <= 1:
                continue
            
            is_strong = raw_word[-1] in STRONG_BREAK
            if is_strong or current_line_len > 10:
                text_line = " ".join([x['word'] for x in current_line_words])
                start_time = current_line_words[0]['start']
                end_time = current_line_words[-1]['end']
                
                if all_lines:
                    prev_end = all_lines[-1]['end']
                    if start_time - prev_end < MIN_GAP:
                        start_time = prev_end + MIN_GAP
                
                all_lines.append({
                    "index": global_index,
                    "start": start_time,
                    "end": end_time,
                    "text": text_line
                })
                global_index += 1
                current_line_words = []
                current_line_len = 0
    
    # 处理剩余内容
    if current_line_words:
        text_line = " ".join([x['word'] for x in current_line_words])
        start_time = current_line_words[0]['start']
        end_time = current_line_words[-1]['end']
        
        if all_lines:
            prev_end = all_lines[-1]['end']
            if start_time - prev_end < MIN_GAP:
                start_time = prev_end + MIN_GAP
        
        all_lines.append({
            "index": global_index,
            "start": start_time,
            "end": end_time,
            "text": text_line
        })
    
    # 写入SRT文件
    logger.info(f"Writing {len(all_lines)} subtitle lines to {output_srt}")
    with open(output_srt, 'w', encoding='utf-8') as f:
        for line in all_lines:
            f.write(f"{line['index']}\n")
            f.write(f"{format_timestamp(line['start'])} --> {format_timestamp(line['end'])}\n")
            f.write(f"{line['text']}\n\n")
    
    # 清理临时文件
    if os.path.exists(temp_audio):
        os.remove(temp_audio)
    
    logger.info("Alignment complete!")

def main():
    parser = argparse.ArgumentParser(description="WhisperX Forced Alignment for TTS Audio")
    parser.add_argument("--analysis", required=True, help="Path to analysis JSON file")
    parser.add_argument("--tts_dir", required=True, help="Directory containing TTS audio files")
    parser.add_argument("--output", required=True, help="Output SRT file path")
    parser.add_argument("--models_dir", default="models", help="Directory to store/load models")
    
    args = parser.parse_args()
    align_segments(args.analysis, args.tts_dir, args.output, args.models_dir)

if __name__ == "__main__":
    main()
