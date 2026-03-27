import json
import requests
import logging
import argparse
import re
import time
import math
import hashlib
from pathlib import Path
from typing import Optional, Dict
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, VIDEO_WIDTH, VIDEO_HEIGHT

# 尝试导入限流管理器
try:
    from utils_rate_limiter import rate_limiter
    _rate_limiter_available = True
except ImportError:
    _rate_limiter_available = False
    logger.warning("限流管理器不可用")

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 翻译缓存
_translation_cache: Dict[str, str] = {}

def _get_cache_key(text: str) -> str:
    """生成缓存键"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:16]

def _get_cached_translation(text: str) -> Optional[str]:
    """获取缓存的翻译"""
    key = _get_cache_key(text)
    return _translation_cache.get(key)

def _set_cached_translation(text: str, translation: str):
    """缓存翻译"""
    key = _get_cache_key(text)
    _translation_cache[key] = translation

def parse_srt(srt_path):
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Matches: Index, Time range, Text
    pattern = re.compile(r'(\d+)\s+(\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2},\d{3})\s+(.*?)(?=\n\n|\n\d+\n|\Z)', re.DOTALL)
    matches = pattern.findall(content)
    
    parsed = []
    for idx, start, end, text in matches:
        parsed.append({
            "id": idx,
            "start": start,
            "end": end,
            "text": text.strip().replace('\n', ' ')
        })
    return parsed

def clean_subtitles(subtitles):
    """
    Merge subtitles that were incorrectly split (e.g., "Dr.", "Speaker:")
    Iteratively merges lines until no more merge conditions are met.
    """
    if not subtitles:
        return []
        
    # Working copy
    cleaned = subtitles[:]
    
    # Common abbreviations that should not end a line
    abbreviations = {
        "Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "St.", "vs.", "etc.", "e.g.", "i.e.", "Jr.", "Sr.",
        "dr.", "mr.", "mrs.", "ms.", "prof.", "st.", "jr.", "sr.", "approx.", "no."
    }
    
    i = 0
    while i < len(cleaned) - 1:
        current = cleaned[i]
        next_sub = cleaned[i+1]
        text = current['text'].strip()
        
        should_merge = False
        
        # Check 1: Ends with Abbreviation
        # We split by space to get the last word
        words = text.split()
        if words:
            last_word = words[-1]
            if last_word in abbreviations:
                should_merge = True
        
        # Check 2: Speaker Label (Short text ending with colon)
        # E.g. "David:" or "Narrator:"
        if not should_merge and text.endswith(":") and len(text) < 25:
            should_merge = True
            
        # Check 3: Sentence fragment not ending in punctuation (Optional, but "Dr." covers most)
        # If we want to be more aggressive:
        # if not text[-1] in ".?!": should_merge = True? 
        # No, that might merge valid pauses. Stick to explicit errors for now.
        
        if should_merge:
            logger.info(f"Merging line {i}: '{text}' + '{next_sub['text']}'")
            # Merge into current
            current['text'] = text + " " + next_sub['text']
            current['end'] = next_sub['end']
            # Remove next_sub
            cleaned.pop(i+1)
            # Do NOT increment i, so we re-evaluate the new merged line
        else:
            i += 1
            
    return cleaned

def translate_batch(texts):
    """
    Translate a list of texts using DeepSeek.
    
    优化点:
    1. 使用缓存避免重复翻译
    2. 使用限流管理器控制API调用速率
    3. 使用字典格式确保对齐
    """
    # 检查缓存
    cached_results = {}
    texts_to_translate = []
    indices_to_translate = []
    
    for i, text in enumerate(texts):
        cached = _get_cached_translation(text)
        if cached:
            cached_results[str(i)] = cached
            logger.debug(f"使用缓存翻译: {text[:30]}... -> {cached[:20]}...")
        else:
            texts_to_translate.append(text)
            indices_to_translate.append(i)
    
    if cached_results:
        logger.info(f"使用 {len(cached_results)} 个缓存翻译")
    
    # 如果全部缓存命中，直接返回
    if not texts_to_translate:
        logger.info("全部翻译已缓存，跳过API调用")
        return [cached_results[str(i)] for i in range(len(texts))]
    
    # 只翻译未缓存的文本
    input_dict = {str(idx): text for idx, text in zip(indices_to_translate, texts_to_translate)}
    
    system_prompt = """
    You are a professional subtitle translator. Translate the following English subtitle lines into concise, natural Chinese.
    
    CRITICAL RULES:
    1. **Format**: Input is a JSON dictionary {id: text}. Output MUST be a JSON dictionary {id: translated_text}.
    2. **Strict Alignment**: Translate ONLY the text provided in the value. Do NOT combine with next lines.
    3. **Fragments**: If a line is a fragment (e.g., "in the"), translate it as a fragment (e.g., "在"). Do NOT complete the sentence using future lines.
    4. **Completeness**: Return a key for EVERY input key.
    
    Example Input: {"0": "I am", "1": "happy"}
    Example Output: {"0": "我", "1": "很开心"}
    """
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(input_dict, ensure_ascii=False)}
        ],
        "response_format": {
            "type": "json_object"
        },
        "temperature": 0.3
    }
    
    def _do_request():
        """执行API请求"""
        response = requests.post(f"{DEEPSEEK_BASE_URL}/chat/completions", headers=headers, json=data)
        response.raise_for_status()
        return response.json()
    
    # 如果有限流管理器，使用它
    result = None
    if _rate_limiter_available:
        try:
            logger.info(f"使用限流管理器进行翻译请求 ({len(texts_to_translate)} 个新文本)")
            result = rate_limiter.execute("deepseek", _do_request)
        except Exception as e:
            logger.error(f"翻译API调用失败(限流控制): {e}")
    else:
        # 回退到原有逻辑
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Translation attempt {attempt + 1}/{max_retries}")
                result = _do_request()
                break
            except Exception as e:
                logger.warning(f"API请求失败 (尝试 {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
    
    if not result:
        logger.error("翻译API调用失败，返回None")
        return None
    
    # 解析结果
    try:
        content_str = result['choices'][0]['message']['content']
        parsed = json.loads(content_str)
        # Ensure it's a dict
        if isinstance(parsed, dict):
            # 合并缓存结果和新翻译结果
            all_results = cached_results.copy()
            
            # 检查新翻译的keys
            missing_keys = []
            for idx in indices_to_translate:
                key = str(idx)
                if key in parsed:
                    translation = parsed[key]
                    all_results[key] = translation
                    # 缓存新翻译
                    _set_cached_translation(texts[idx], translation)
                else:
                    missing_keys.append(key)
            
            if missing_keys:
                logger.warning(f"翻译结果缺少keys: {missing_keys}")
            
            # Convert back to list in order
            output_list = []
            for i in range(len(texts)):
                key = str(i)
                if key in all_results:
                    output_list.append(all_results[key])
                else:
                    logger.warning(f"缺少key {key}，使用原文")
                    output_list.append(texts[i])
            
            logger.info(f"翻译完成: {len(output_list)} 行")
            return output_list
        
        logger.warning(f"意外的JSON格式: {content_str}")
        
    except json.JSONDecodeError:
        logger.error(f"JSON解析失败: {content_str}")
    except Exception as e:
        logger.error(f"翻译结果处理失败: {e}")
    
    # 出错时回退到原文，但标记为未翻译
    logger.warning("翻译失败，使用标记原文")
    return [f"[待译]{text}" for text in texts]

def smart_split_text(text, max_chars):
    """
    Split text into chunks of at most max_chars, aiming for balanced lengths
    and preferring splits after punctuation marks.
    """
    length = len(text)
    if length <= max_chars:
        return [text]
    
    # Calculate target number of columns to avoid short trailing columns
    # E.g. 20 chars, max 16 -> 2 cols (10, 10) instead of (16, 4)
    num_cols = math.ceil(length / max_chars)
    
    chunks = []
    current_text = text
    
    # Punctuation to prefer breaking AFTER
    punctuations = "，。？！：；,.:;?!、 "
    
    for i in range(num_cols - 1):
        # Calculate target length for this chunk to keep remaining chunks balanced
        remaining_len = len(current_text)
        remaining_cols = num_cols - i
        target_len = int(remaining_len / remaining_cols)
        
        # Search window: centered on target_len, +/- 4 chars
        start_search = max(1, target_len - 4)
        end_search = min(remaining_len, target_len + 5)
        
        best_split = min(target_len, max_chars) # Default to balanced split
        
        min_dist = float('inf')
        
        # Search for punctuation
        for idx in range(start_search, end_search):
            split_point = idx + 1
            
            # Constraint: Chunk cannot exceed max_chars
            if split_point > max_chars:
                continue
                
            char = current_text[idx]
            if char in punctuations:
                dist = abs(split_point - target_len)
                # If multiple punctuations, pick closest to target length
                if dist < min_dist:
                    min_dist = dist
                    best_split = split_point
        
        chunks.append(current_text[:best_split])
        current_text = current_text[best_split:]
        
    # Append remainder
    if current_text:
        chunks.append(current_text)
        
    return chunks

def make_vertical(text):
    r"""
    Insert \N after every character to force vertical layout.
    """
    return r'\N'.join(list(text))

def generate_ass(subtitles, ass_path, video_w=VIDEO_WIDTH, video_h=VIDEO_HEIGHT):
    """
    Generate ASS file with:
    1. Vertical Chinese subtitles on the right (VerticalZH)
    2. Horizontal English subtitles at the bottom (English)
    """
    # Style Config
    
    # 1. Vertical Chinese (Right)
    # FontSize: 4.5% of height (Increased from 3.5% for better visibility)
    zh_font_size = int(video_h * 0.045)
    # MarginR: 5% of width
    zh_margin_r = int(video_w * 0.05)
    # MarginV: 10% of height (User request: middle 4/5 = 10% top + 10% bottom)
    zh_margin_v = int(video_h * 0.1)
    
    # Calculate max characters per vertical column to stay within 4/5 height
    # usable_height = video_h * 0.8
    # safe_chars = usable_height / font_size
    # We use 0.8 factor strictly.
    max_chars_per_col = int((video_h * 0.8) / zh_font_size)
    # Column spacing (gap between vertical lines)
    col_spacing = int(zh_font_size * 1.2) # Font size + 20% gap
    
    # 2. Horizontal English (Bottom)
    # FontSize: 7.5% of height (Restored to large size)
    en_font_size = int(video_h * 0.075)
    # MarginV: 5% of height
    en_margin_v = int(video_h * 0.05)
    # MarginH: 10% of width (Fix: Enforce 4/5 width limit to prevent overflow)
    en_margin_h = int(video_w * 0.1)
    
    # Outline: Thin
    outline = int(video_h * 0.002) # ~4px
    if outline < 2: outline = 2
    
    # Header with Styles
    # Note: Using "Microsoft YaHei" for Chinese to ensure glyph visibility on Windows
    header = f"""[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayResX: {video_w}
PlayResY: {video_h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: VerticalZH,Microsoft YaHei,{zh_font_size},&H00DDDDDD,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{outline},0,6,100,{zh_margin_r},{zh_margin_v},1
Style: English,Arial,{en_font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,3,{outline},0,2,{en_margin_h},{en_margin_h},{en_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    events = []
    
    def convert_time(srt_time):
        # 00:00:00,742 -> 0:00:00.74 (ASS格式：厘秒，2位小数)
        h, m, s_ms = srt_time.split(':')
        s, ms = s_ms.split(',')
        return f"{int(h)}:{m}:{s}.{ms[:2]}"
    
    def split_en_for_display(text, max_words=12):
        """把长英文文本拆成 ASS \\N 换行的短行（纯视觉，不影响时间）"""
        import re
        words = text.split()
        if len(words) <= max_words:
            return text
        
        # 在标点处拆分
        lines = []
        current = []
        for word in words:
            current.append(word)
            word_count = len(current)
            # 在句号/问号/叹号/分号后切分
            if word_count >= max_words or (word_count > 5 and word[-1] in '.?!;'):
                lines.append(' '.join(current))
                current = []
            # 在逗号后，如果已经足够长则切分
            elif word_count > 8 and word[-1] == ',':
                lines.append(' '.join(current))
                current = []
        if current:
            lines.append(' '.join(current))
        
        return '\\N'.join(lines)
    
    for idx, sub in enumerate(subtitles):
        # 不做时间调整——SRT 的段级时间戳已经准确
        start_ass = convert_time(sub['start'])
        end_ass = convert_time(sub['end'])
        
        # 1. Chinese (Vertical with Auto-Wrapping)
        # Split text into columns using smart split logic
        zh_text_full = sub['text_zh']
        
        chunks = smart_split_text(zh_text_full, max_chars_per_col)
        
        # 计算固定位置：右侧，垂直居中
        # x = 视频宽度 - 右边距
        # y = 垂直中心
        base_x = video_w - zh_margin_r
        base_y = video_h // 2
        
        for i, chunk in enumerate(chunks):
            # Verticalize the chunk
            text_vert = make_vertical(chunk)
            
            # 计算这一列的x位置（从右向左排列）
            # 第0列在最右边，第1列在左边
            col_x = base_x - (i * col_spacing)
            
            # 使用\pos固定位置，\an6表示右中对齐
            # 这样所有列都在同一时间段显示，位置固定
            events.append(f"Dialogue: 0,{start_ass},{end_ass},VerticalZH,,0,0,0,,{{\\an6\\pos({col_x},{base_y})}}{text_vert}")
        
        # 2. English (Horizontal, with line breaks for long text)
        text_en = sub['text'].replace('\n', ' ')
        # 长文本用 \N 换行拆成视觉短行（不影响时间戳）
        text_en_display = split_en_for_display(text_en, max_words=12)
        
        # 2026 Fix: Use explicit \pos(x,y) to lock position and prevent collision jumping
        # x = Center, y = Bottom Margin Line
        pos_x = int(video_w / 2)
        pos_y = int(video_h - en_margin_v)
        
        # \an2 sets anchor to Bottom Center. \pos sets the coordinate of that anchor.
        events.append(f"Dialogue: 0,{start_ass},{end_ass},English,,0,0,0,,{{\\an2\\pos({pos_x},{pos_y})}}{text_en_display}")
        
    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write(header + "\n".join(events))
    
    logger.info(f"Generated Bilingual subtitles at {ass_path}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--srt_path", type=Path, help="Path to input English SRT")
    parser.add_argument("--output_dir", type=Path, help="Directory to save output")
    args = parser.parse_args()
    
    if not args.srt_path.exists():
        logger.error(f"SRT file not found: {args.srt_path}")
        return

    # 1. Parse
    subtitles = parse_srt(args.srt_path)
    if not subtitles:
        logger.error("No subtitles found.")
        return
        
    # 1.5 Clean Subtitles (Merge incorrect splits like "Dr." or "David:")
    logger.info("Cleaning and merging subtitles...")
    subtitles = clean_subtitles(subtitles)
        
    # 2. Translate
    logger.info("Translating subtitles...")
    texts = [s['text'] for s in subtitles]
    
    # Batch if too long (DeepSeek has 32k context, usually fine for short videos, but good practice to batch)
    # For now, just send all.
    logger.info(f"Translating {len(texts)} lines...")
    translated_texts = translate_batch(texts)
    
    # 处理翻译失败的情况
    if translated_texts is None:
        logger.error("翻译失败，使用备用翻译方案")
        # 使用简单的备用翻译（这里可以用其他翻译API或标记需要人工检查）
        translated_texts = [f"[待翻译] {text}" for text in texts]
    
    if len(translated_texts) != len(subtitles):
        logger.warning(f"Translation count mismatch. Input: {len(subtitles)}, Output: {len(translated_texts)}")
        logger.debug(f"Input: {texts}")
        logger.debug(f"Output: {translated_texts}")
        # Handle mismatch simplistic
        if len(translated_texts) < len(subtitles):
            translated_texts.extend(["[翻译缺失]"] * (len(subtitles) - len(translated_texts)))
        else:
            translated_texts = translated_texts[:len(subtitles)]
            
    for sub, zh in zip(subtitles, translated_texts):
        sub['text_zh'] = zh
        
    # 3. Generate ASS
    ass_path = args.output_dir / "subtitles_zh.ass"
    generate_ass(subtitles, ass_path)

if __name__ == "__main__":
    main()
