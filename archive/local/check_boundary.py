import re

def parse_ass_time(time_str):
    parts = time_str.split(':')
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])

with open('workspace/temp/1初阶_20260218_183018/output/subtitles_zh.ass', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 检查segment边界附近的字幕
segment_boundaries = [0, 26.27, 46.14, 60.54, 81.61, 101.74, 125.74]

print("Checking subtitles around segment boundaries:")
for boundary in segment_boundaries:
    print(f"\n=== Around {boundary:.2f}s (segment boundary) ===")
    for line in lines:
        if line.startswith('Dialogue:'):
            parts = line.split(',')
            start_time = parse_ass_time(parts[1])
            end_time = parse_ass_time(parts[2])
            
            # 检查是否在边界附近
            if abs(start_time - boundary) < 2 or abs(end_time - boundary) < 2 or (start_time < boundary < end_time):
                text = ','.join(parts[9:]).strip() if len(parts) > 9 else ''
                print(f"  {start_time:.3f}s - {end_time:.3f}s: {text[:40]}...")
