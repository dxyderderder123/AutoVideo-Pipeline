import json
import wave
import os

# 检查音频文件时长
tts_dir = 'workspace/temp/1初阶_20260218_183018/tts'
audio_durations = []
for i in range(1, 8):
    audio_path = os.path.join(tts_dir, f'{i}.wav')
    if os.path.exists(audio_path):
        with wave.open(audio_path, 'rb') as f:
            frames = f.getnframes()
            rate = f.getframerate()
            duration = frames / rate
            audio_durations.append((i, duration))
            print(f"Audio {i}: {duration:.2f}s")

print(f"\nTotal audio: {sum(d for _, d in audio_durations):.2f}s")

# 检查analysis.json中的时长
with open('workspace/temp/1初阶_20260218_183018/analysis_merged.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print("\nAnalysis durations:")
total_analysis = 0
for seg in data['segments']:
    print(f"Segment {seg['id']}: {seg['duration']:.2f}s")
    total_analysis += seg['duration']
print(f"\nTotal analysis: {total_analysis:.2f}s")

# 检查SRT字幕时间
print("\nSRT subtitle times:")
with open('workspace/temp/1初阶_20260218_183018/output/subtitles.srt', 'r') as f:
    lines = f.readlines()
    for i, line in enumerate(lines):
        if '-->' in line:
            print(f"Line {i//4+1}: {line.strip()}")
