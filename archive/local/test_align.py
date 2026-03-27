import whisperx
import torch
import json
import subprocess
import os

tts_dir = 'workspace/temp/1初阶_20260218_183018/tts'
output_dir = 'workspace/temp/1初阶_20260218_183018/output'

# 获取音频文件列表
audio_files = []
for i in range(1, 8):
    path = os.path.join(tts_dir, f'{i}.wav')
    if os.path.exists(path):
        audio_files.append(path)

print(f"Found {len(audio_files)} audio files")

# 合并音频
list_file = os.path.join(output_dir, 'test_list.txt')
with open(list_file, 'w') as f:
    for af in audio_files:
        f.write(f"file '{os.path.abspath(af)}'\n")

combined_audio = os.path.join(output_dir, 'test_combined.wav')
cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", combined_audio]
result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode != 0:
    print(f"ffmpeg error: {result.stderr}")
    exit(1)
print(f"Combined audio created: {os.path.exists(combined_audio)}")

# 获取合并后的音频时长
result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", 
                        "-of", "default=noprint_wrappers=1:nokey=1", combined_audio],
                       capture_output=True, text=True)
duration_str = result.stdout.strip()
print(f"ffprobe output: '{duration_str}'")
if duration_str:
    total_duration = float(duration_str)
else:
    # 使用备用方法
    import wave
    with wave.open(combined_audio, 'rb') as f:
        frames = f.getnframes()
        rate = f.getframerate()
        total_duration = frames / rate
print(f"Combined audio duration: {total_duration:.2f}s")

# 加载模型
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f"Using device: {device}")
model, metadata = whisperx.load_align_model(language_code='en', device=device)

# 加载音频
audio = whisperx.load_audio(combined_audio)

# 加载analysis
with open('workspace/temp/1初阶_20260218_183018/analysis_merged.json', 'r') as f:
    data = json.load(f)

segments = data['segments']

# 创建transcript
transcript = []
current_offset = 0.0
for seg in segments:
    duration = seg['duration']
    transcript.append({
        "text": seg['text'],
        "start": current_offset,
        "end": current_offset + duration
    })
    print(f"Segment {seg['id']}: {current_offset:.2f}s - {current_offset + duration:.2f}s")
    current_offset += duration

# 对齐
print("\nPerforming alignment...")
result = whisperx.align(transcript, model, metadata, audio, device, return_char_alignments=False)

words = result.get('word_segments', [])
print(f"\nTotal words aligned: {len(words)}")

# 打印前30个单词的时间戳
print("\nFirst 30 words:")
for i, w in enumerate(words[:30]):
    word = w.get('word', '?')
    start = w.get('start', 0)
    end = w.get('end', 0)
    print(f"{i}: '{word}' - {start:.3f}s - {end:.3f}s")

# 检查是否有大的时间间隙
print("\nChecking for time gaps...")
for i in range(1, min(30, len(words))):
    prev_end = words[i-1].get('end', 0)
    curr_start = words[i].get('start', 0)
    gap = curr_start - prev_end
    if gap > 0.5:
        print(f"Gap of {gap:.3f}s between '{words[i-1].get('word')}' and '{words[i].get('word')}'")

# 清理
os.remove(list_file)
os.remove(combined_audio)
