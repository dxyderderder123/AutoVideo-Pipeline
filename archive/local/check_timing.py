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
            print(f"Audio {i}: {duration:.6f}s")

print(f"\nTotal audio: {sum(d for _, d in audio_durations):.6f}s")

# 检查filter_complex_script.txt中的时长
with open('workspace/temp/1初阶_20260218_183018/output/filter_complex_script.txt', 'r') as f:
    content = f.read()

import re
# 提取trim=duration=xxx
durations = re.findall(r'trim=duration=([\d.]+)', content)
print(f"\nFilter durations: {durations}")
total_filter = sum(float(d) for d in durations)
print(f"Total filter duration: {total_filter:.6f}s")

# 检查视频实际时长
import subprocess
result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
                        '-of', 'default=noprint_wrappers=1:nokey=1', 
                        'workspace/temp/1初阶_20260218_183018/output/final_video.mp4'],
                       capture_output=True, text=True)
print(f"\nFinal video duration: {result.stdout.strip()}s")
