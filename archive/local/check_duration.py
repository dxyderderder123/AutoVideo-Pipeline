import json
with open('workspace/temp/1初阶_20260218_183018/analysis_merged.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
total = 0
for seg in data['segments']:
    print(f"Segment {seg['id']}: duration={seg['duration']:.2f}s")
    total += seg['duration']
print(f"\nTotal duration: {total:.2f}s")
