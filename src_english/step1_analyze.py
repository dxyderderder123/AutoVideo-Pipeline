import json
import os
import re
import requests
import logging
import time
import hashlib
from pathlib import Path
from typing import Optional, Dict, List
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

# 导入限流管理器
try:
    from utils_rate_limiter import rate_limiter, rate_limited
except ImportError:
    rate_limiter = None
    rate_limited = None

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 关键词缓存
_keywords_cache: Dict[str, List[str]] = {}
_tags_cache: Dict[str, List[str]] = {}

def _get_cache_key(text: str) -> str:
    """生成文本的缓存键"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:16]

def _get_cached_keywords(text: str) -> Optional[List[str]]:
    """获取缓存的关键词"""
    key = _get_cache_key(text)
    return _keywords_cache.get(key)

def _set_cached_keywords(text: str, keywords: List[str]):
    """缓存关键词"""
    key = _get_cache_key(text)
    _keywords_cache[key] = keywords

def _normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([.!?])([A-Z])", r"\1 \2", text)
    text = re.sub(r'([.!?])(["\'])([A-Z])', r"\1 \2\3", text)
    return text

def _split_sentences(text: str) -> list[str]:
    abbreviations = {
        "Dr.", "Mr.", "Mrs.", "Ms.", "Prof.", "St.", "vs.", "etc.", "e.g.", "i.e.", "Jr.", "Sr.",
        "dr.", "mr.", "mrs.", "ms.", "prof.", "st.", "jr.", "sr.", "approx.", "no."
    }
    protected = text
    for abbr in abbreviations:
        protected = protected.replace(abbr, abbr.replace(".", "<DOT>"))
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'])', protected.strip())
    out = []
    for p in parts:
        p = p.replace("<DOT>", ".").strip()
        if p:
            out.append(p)
    return out

def _build_segments(title: str, body_text: str) -> list[dict]:
    body_text = _normalize_whitespace(body_text)
    if not body_text:
        return [{"id": "1", "text": _normalize_whitespace(title), "video_keywords": []}]

    sentences = _split_sentences(body_text)
    total_words = sum(len(s.split()) for s in sentences)

    fast_mode = os.environ.get("SELF_MEDIA_FAST_MODE", "").strip() == "1"
    try:
        target_segments = int(os.environ.get("SELF_MEDIA_TARGET_SEGMENTS", "").strip() or "0")
    except Exception:
        target_segments = 0

    if target_segments > 0 and total_words > 0:
        target_words = max(35, min(140, int(round(total_words / target_segments))))
        max_words = max(45, min(140, target_words + 12))
        flush_words = max(30, min(max_words - 8, target_words))
        min_last_words = max(20, min(60, target_words // 2))
    else:
        if fast_mode:
            max_words = 110
            flush_words = 85
            min_last_words = 30
        else:
            max_words = 75
            flush_words = 55
            min_last_words = 25

    segments_text: list[str] = []
    current: list[str] = []
    current_wc = 0

    def flush():
        nonlocal current, current_wc
        if current:
            segments_text.append(" ".join(current).strip())
        current = []
        current_wc = 0

    for s in sentences:
        s_wc = len(s.split())
        if current and (current_wc + s_wc) > max_words:
            flush()
        current.append(s)
        current_wc += s_wc
        if current_wc >= flush_words:
            flush()
    flush()

    if len(segments_text) >= 2:
        if len(segments_text[-1].split()) < min_last_words:
            segments_text[-2] = f"{segments_text[-2]} {segments_text[-1]}".strip()
            segments_text.pop()

    if segments_text:
        first = segments_text[0].strip()
        if title and not first.lower().startswith(title.strip().lower()):
            t = title.strip()
            if t.endswith((".", "!", "?", "…")):
                segments_text[0] = f"{t} {first}"
            else:
                segments_text[0] = f"{t}. {first}"

    segments = []
    for idx, text in enumerate(segments_text, start=1):
        segments.append({"id": str(idx), "text": text, "video_keywords": []})
    return segments

def _deepseek_chat(messages: list[dict], timeout: int = 90, max_retries: int = 3) -> dict | None:
    """
    调用DeepSeek API，带限流保护
    
    如果限流管理器可用，会使用统一的限流控制。
    否则回退到原有的简单重试逻辑。
    """
    def _do_request():
        response = requests.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek-chat",
                "messages": messages,
                "temperature": 0.4,
                "response_format": {"type": "json_object"}
            },
            timeout=timeout
        )
        response.raise_for_status()
        result = response.json()
        content_str = result["choices"][0]["message"]["content"]
        if content_str.startswith("```json"):
            content_str = content_str[7:]
        if content_str.startswith("```"):
            content_str = content_str[3:]
        if content_str.endswith("```"):
            content_str = content_str[:-3]
        content_str = content_str.strip()
        return json.loads(content_str)
    
    # 如果有限流管理器，使用它
    if rate_limiter is not None:
        try:
            return rate_limiter.execute("deepseek", _do_request)
        except Exception as e:
            logger.error(f"DeepSeek API调用失败(限流控制): {e}")
            return None
    
    # 回退到原有逻辑
    for attempt in range(max_retries):
        try:
            return _do_request()
        except Exception as e:
            logger.warning(f"DeepSeek API failed (Attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
    return None

def _fill_keywords_and_tags(title: str, segments: list[dict]) -> dict:
    """
    为每个片段生成视频关键词和标签
    
    优化点:
    1. 使用关键词缓存避免重复API调用
    2. 批量处理API请求
    3. 限流保护
    """
    # 1. 生成Tags (使用缓存)
    tags: list[str] = []
    tag_cache_key = _get_cache_key(title)
    
    if tag_cache_key in _tags_cache:
        tags = _tags_cache[tag_cache_key]
        logger.info(f"使用缓存的Tags: {tags}")
    else:
        try:
            tag_context = " ".join([s.get("text", "") for s in segments[:3]]).strip()
            messages = [
                {
                    "role": "system",
                    "content": "Generate Bilibili tags. Return JSON only: {\"tags\": [5 strings]}. Chinese preferred.",
                },
                {"role": "user", "content": f"Title: {title}\n\nContent:\n{tag_context}"},
            ]
            res = _deepseek_chat(messages)
            if res and isinstance(res.get("tags"), list):
                tags = [str(x).strip() for x in res["tags"] if str(x).strip()][:5]
                _tags_cache[tag_cache_key] = tags
        except Exception as e:
            logger.warning(f"生成Tags失败: {e}")
    
    if len(tags) != 5:
        tags = ["英语学习", "心理健康", "心理学", "囤积症", "知识科普"]

    # 2. 生成Video Keywords (使用缓存)
    system_prompt = """
You are a professional video director. Generate VIDEO_KEYWORDS for each segment.

Rules:
- VIDEO_KEYWORDS: 3 to 5 single words or short phrases.
- THINK LIKE A CAMERA: physical objects/people/scenes only.
- Avoid abstract words (psychology, concept, strategy, success, failure, etc).

Return JSON strictly:
{"segments":[{"id":"1","video_keywords":["..."]},...]}
"""
    
    id_to_kw: dict[str, list[str]] = {}
    uncached_segments = []
    
    # 先检查缓存
    for s in segments:
        seg_text = s.get("text", "")
        cached_kw = _get_cached_keywords(seg_text)
        if cached_kw:
            id_to_kw[str(s["id"])] = cached_kw
            logger.debug(f"片段 {s['id']} 使用缓存关键词")
        else:
            uncached_segments.append(s)
    
    # 对未缓存的片段批量请求API
    if uncached_segments:
        batch_size = 10
        for start in range(0, len(uncached_segments), batch_size):
            chunk = [{"id": s["id"], "text": s["text"]} for s in uncached_segments[start:start + batch_size]]
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps({"segments": chunk}, ensure_ascii=False)},
            ]
            
            logger.info(f"请求关键词生成: 批次 {start//batch_size + 1} ({len(chunk)}个片段)")
            res = _deepseek_chat(messages)
            
            if not res:
                logger.warning(f"关键词生成API返回空结果")
                continue
                
            for item in res.get("segments", []) or []:
                seg_id = str(item.get("id", "")).strip()
                kw = item.get("video_keywords", [])
                if not seg_id or not isinstance(kw, list):
                    continue
                cleaned = [str(x).strip() for x in kw if str(x).strip()]
                if cleaned:
                    id_to_kw[seg_id] = cleaned[:5]
                    # 缓存结果
                    seg_text = next((s.get("text", "") for s in uncached_segments if str(s["id"]) == seg_id), "")
                    if seg_text:
                        _set_cached_keywords(seg_text, cleaned[:5])

    # 填充所有片段的关键词
    for s in segments:
        seg_id = str(s["id"])
        kw = id_to_kw.get(seg_id)
        if kw:
            s["video_keywords"] = kw
        else:
            s["video_keywords"] = ["nature"]
            logger.warning(f"片段 {seg_id} 未获取到关键词，使用默认值")

    return {"tags": tags, "segments": segments}

def analyze_text(input_file: Path, output_file: Path):
    logger.info(f"Start analyzing text from: {input_file}")
    
    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        return None

    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    # Content Cleaning Logic (Added per user request)
    # Remove lines 2 and 3 if they match the specific pattern (Metadata/Translation)
    # Pattern: 
    # Line 2 usually contains Chinese translation of title or metadata
    # Line 3 usually contains "难度：... 单词：... 读后感：..."
    if len(lines) >= 3:
        line3 = lines[2].strip()
        if "难度：" in line3 or "单词：" in line3 or "读后感：" in line3:
            logger.info("Detected metadata in line 3. Removing lines 2 and 3.")
            # Keep line 1 (Title), Remove 2 & 3, Keep rest
            # Note: lines is 0-indexed. 
            # lines[0] = Title
            # lines[1] = Translation (Remove)
            # lines[2] = Metadata (Remove)
            # lines[3:] = Content
            cleaned_content = lines[0] + "".join(lines[3:])
        else:
            cleaned_content = "".join(lines)
    else:
        cleaned_content = "".join(lines)

    content = cleaned_content

    try:
        mode = os.environ.get("SELF_MEDIA_STEP1_MODE", "deterministic").strip().lower()
        if mode == "llm":
            system_prompt = """
You are a professional video director and editor. Your task is to analyze the provided article and segment it into video scenes.

Return JSON:
{"tags":[...5...],"segments":[{"id":"1","text":"...","video_keywords":["..."]},...]}
"""
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ]
            logger.info("Sending request to DeepSeek API (single-call mode)...")
            parsed_json = _deepseek_chat(messages, timeout=90, max_retries=3)
            if not parsed_json:
                return None
        else:
            title_line = lines[0].strip() if lines else ""
            if len(lines) >= 3 and ("难度：" in lines[2] or "单词：" in lines[2] or "读后感：" in lines[2]):
                body_text = "".join(lines[3:])
            else:
                body_text = "".join(lines[1:])
            segments = _build_segments(title_line, body_text)
            logger.info(f"Built {len(segments)} segments (deterministic full-text).")
            parsed_json = _fill_keywords_and_tags(title_line, segments)

        # Post-process: Estimate duration for parallel processing
        for seg in parsed_json.get("segments", []):
            text = seg.get("text", "")
            # Estimate duration:
            # English TTS (VibeVoice) Analysis (2026-02-13):
            # Statistical Average: 0.554 sec/word (Calculated from project history via tools/calculate_wpm.py)
            # To prevent video looping (playing twice), we must OVERESTIMATE the duration.
            # We use a safety factor of 1.2x (approx 0.66s/word) to ensure video is long enough coverage.
            STATISTICAL_AVG_SEC_PER_WORD = 0.554
            SAFETY_FACTOR = 1.2
            SAFE_SEC_PER_WORD = STATISTICAL_AVG_SEC_PER_WORD * SAFETY_FACTOR # ~0.665

            word_count = len(text.split())
            estimated_duration = (word_count * SAFE_SEC_PER_WORD) + 2.0 # Buffer
            seg["duration"] = round(estimated_duration, 2)
            seg["word_count"] = word_count
        
        # Save to output_file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(parsed_json, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Analysis complete. Saved to {output_file}")
        return parsed_json
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return None

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file", type=Path, help="Path to input markdown file")
    parser.add_argument("output_file", type=Path, help="Path to output json file")
    args = parser.parse_args()
    
    analyze_text(args.input_file, args.output_file)
