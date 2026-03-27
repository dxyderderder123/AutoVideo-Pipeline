import re

def parse_ass_time(time_str):
    parts = time_str.split(':')
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])

with open('workspace/temp/1初阶_20260218_185652/output/subtitles_zh.ass', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("Subtitles around 9 seconds:")
for line in lines:
    if line.startswith('Dialogue:'):
        parts = line.split(',')
        start_time = parse_ass_time(parts[1])
        end_time = parse_ass_time(parts[2])
        
        if 7 < start_time < 12 or 7 < end_time < 12 or (start_time < 9 < end_time):
            text = ','.join(parts[9:]).strip() if len(parts) > 9 else ''
            print(f"{start_time:.2f}s - {end_time:.2f}s: {text[:50]}...")
