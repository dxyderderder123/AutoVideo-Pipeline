import whisperx
import torch
import json
import subprocess
import os
import wave

# 直接使用第一个音频文件测试
audio_path = r'V:\Default\Desktop\Self-media\workspace\temp\1初阶_20260218_183018\tts\1.wav'

# 获取音频时长
with wave.open(audio_path, 'rb') as f:
    frames = f.getnframes()
    rate = f.getframerate()
    duration = frames / rate
print(f"Audio duration: {duration:.2f}s")

# 加载模型
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f"Using device: {device}")
model, metadata = whisperx.load_align_model(language_code='en', device=device)

# 加载音频
audio = whisperx.load_audio(audio_path)

# 文本
text = 'From Locks to Websites: The Benefits of Absorption. Louis XVI is often depicted as a dull king, whose only accomplishment was being beheaded in the French Revolution. I was surprised to learn recently that he was an avid locksmith and blacksmith. Why would a king with the freedom to do nearly anything he wanted get his hands dirty doing the work of a commoner?'

transcript = [{'text': text, 'start': 0.0, 'end': duration}]

# 对齐
print("\nPerforming alignment...")
result = whisperx.align(transcript, model, metadata, audio, device, return_char_alignments=False)

words = result.get('word_segments', [])
print(f"\nTotal words aligned: {len(words)}")

# 打印所有单词的时间戳
print("\nAll words with timestamps:")
for i, w in enumerate(words):
    word = w.get('word', '?')
    start = w.get('start', 0)
    end = w.get('end', 0)
    print(f"{i}: '{word}' - {start:.3f}s - {end:.3f}s")

# 检查是否有大的时间间隙
print("\nChecking for time gaps > 0.5s:")
for i in range(1, len(words)):
    prev_end = words[i-1].get('end', 0)
    curr_start = words[i].get('start', 0)
    gap = curr_start - prev_end
    if gap > 0.5:
        print(f"Gap of {gap:.3f}s between '{words[i-1].get('word')}' and '{words[i].get('word')}'")
