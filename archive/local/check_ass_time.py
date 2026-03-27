# ASS时间格式应该是 H:MM:SS.CC (厘秒，2位小数)
# SRT时间格式是 H:MM:SS,MMM (毫秒，3位小数)

# 检查ASS文件中的时间格式
with open('workspace/temp/1初阶_20260218_183018/output/subtitles_zh.ass', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("ASS time format check:")
for line in lines[:20]:
    if line.startswith('Dialogue:'):
        parts = line.split(',')
        start = parts[1]
        end = parts[2]
        print(f"Start: '{start}', End: '{end}'")
        
        # 检查格式
        # ASS格式: 0:00:00.00 (小时:分钟:秒.厘秒)
        # 错误格式: 0:00:00.000 (3位小数)
        if '.' in start:
            decimal_part = start.split('.')[1]
            if len(decimal_part) == 3:
                print(f"  WARNING: 3 decimal places (should be 2 for ASS)")
