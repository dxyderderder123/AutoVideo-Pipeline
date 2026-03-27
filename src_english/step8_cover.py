import argparse
import os
import requests
import textwrap
import hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import logging
import sys
from openai import OpenAI
from urllib.parse import urlsplit, urlunsplit
from typing import Optional, Dict, Tuple

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import SILICON_CLOUD_API_KEY, COVER_MODEL, COVER_PROMPT, COVER_FONT_PATH, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

# Configure logging
_log_level = os.environ.get("SELF_MEDIA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _log_level, logging.INFO), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import time
import random

# 尝试导入限流管理器
try:
    from utils_rate_limiter import rate_limiter
    _rate_limiter_available = True
except ImportError:
    _rate_limiter_available = False
    logger.warning("限流管理器不可用")

# 封面缓存
_cover_cache: Dict[str, Tuple[Path, Path]] = {}

def _get_cover_cache_key(title: str, content: str) -> str:
    """生成封面缓存键"""
    content_hash = hashlib.md5(f"{title}:{content[:200]}".encode()).hexdigest()[:16]
    return content_hash

def _get_cached_cover(title: str, content: str) -> Optional[Tuple[Path, Path]]:
    """获取缓存的封面路径 (horizontal, vertical)"""
    key = _get_cover_cache_key(title, content)
    cached = _cover_cache.get(key)
    if cached and cached[0].exists() and cached[1].exists():
        return cached
    return None

def _set_cached_cover(title: str, content: str, horizontal: Path, vertical: Path):
    """缓存封面"""
    key = _get_cover_cache_key(title, content)
    _cover_cache[key] = (horizontal, vertical)

def generate_cover_prompt(content, title):
    """Use DeepSeek to generate a context-aware prompt for Flux.1 based on the content."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
            
            system_prompt = (
                "You are an expert Minimalist Art Director specializing in abstract line art.\n"
                "Your task is to write a precise English prompt for the Kwai-Kolors image generation model based on the provided text content.\n"
                "Requirements:\n"
                "1. Style: Minimalist Line Art, Abstract Single Line Drawing, Matisse/Picasso style. Bold black lines on white/neutral background. High contrast. NO shading, NO realism, NO watercolors.\n"
                "2. Content: Abstract the core metaphor of the text into a simple, symbolic line drawing.\n"
                "   - If 'grieving a book', draw a simple outline of a book with a tear drop or a broken heart line.\n"
                "   - If 'productivity', draw a simple geometric stack of blocks.\n"
                "3. Composition: Clean, spacious, with a clear central subject. Massive negative space.\n"
                "4. NO TEXT: The image must NOT contain any text.\n"
                "5. Output Format: Return ONLY the prompt string. No explanations."
            )
            
            user_content = f"Title: {title}\n\nContent Excerpt:\n{content[:500]}..." # Use first 500 chars for context
            
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                stream=False
            )
            
            generated_prompt = response.choices[0].message.content.strip()
            logger.info(f"Generated Flux Prompt: {generated_prompt}")
            return generated_prompt
            
        except Exception as e:
            logger.warning(f"Attempt {attempt+1}/{max_retries} failed to generate prompt via DeepSeek: {e}")
            if attempt < max_retries - 1:
                time.sleep(random.uniform(1.0, 3.0))
            else:
                logger.error("All attempts failed. Falling back to default prompt.")
                return COVER_PROMPT

def generate_base_image(output_path, prompt):
    """Call SiliconCloud API to generate the base image."""
    url = "https://api.siliconflow.cn/v1/images/generations"
    
    headers = {
        "Authorization": f"Bearer {SILICON_CLOUD_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": COVER_MODEL,
        "prompt": prompt,
        "image_size": "1024x1024",
        "batch_size": 1,
        "num_inference_steps": 20,
        "guidance_scale": 5.0
    }
    
    logger.info(f"Requesting image generation from {COVER_MODEL}...")
    
    def _do_request():
        """执行API请求"""
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        return response.json()
    
    # 如果有限流管理器，使用它
    if _rate_limiter_available:
        try:
            logger.info("使用限流管理器进行封面生成")
            result = rate_limiter.execute("silicon_cloud", _do_request)
            
            image_url = result['data'][0]['url']
            try:
                parts = urlsplit(image_url)
                safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            except Exception:
                safe_url = "<redacted>"
            logger.info(f"Image generated successfully: {safe_url}")
            
            # Download image
            img_response = requests.get(image_url)
            with open(output_path, 'wb') as f:
                f.write(img_response.content)
            logger.info(f"Base image saved to {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"封面生成失败(限流控制): {e}")
            # Fallback to placeholder
            logger.warning("Generating placeholder image due to API failure.")
            img = Image.new('RGB', (1024, 1024), color = (40, 44, 52))
            img.save(output_path)
            return True
    
    # 回退到原有逻辑
    max_retries = 3
    for attempt in range(max_retries):
        try:
            result = _do_request()
            
            image_url = result['data'][0]['url']
            try:
                parts = urlsplit(image_url)
                safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            except Exception:
                safe_url = "<redacted>"
            logger.info(f"Image generated successfully: {safe_url}")
            
            # Download image
            img_response = requests.get(image_url)
            with open(output_path, 'wb') as f:
                f.write(img_response.content)
            logger.info(f"Base image saved to {output_path}")
            return True
            
        except Exception as e:
            logger.warning(f"Attempt {attempt+1}/{max_retries} failed to generate image: {e}")
            if attempt < max_retries - 1:
                time.sleep(random.uniform(2.0, 5.0))
            else:
                logger.error(f"All attempts failed: {e}")
                # ALWAYS fallback to placeholder to prevent pipeline crash
                logger.warning("Generating placeholder image due to API failure.")
                img = Image.new('RGB', (1024, 1024), color = (40, 44, 52))
                img.save(output_path)
                return True

def add_text_to_image(image_path, title, output_path, target_ratio=(4, 3)):
    """Crop image and overlay text."""
    try:
        with Image.open(image_path) as img:
            # 1. Crop to target ratio
            width, height = img.size
            target_w, target_h = target_ratio
            
            # Calculate crop box (Center Crop)
            current_ratio = width / height
            desired_ratio = target_w / target_h
            
            if current_ratio > desired_ratio:
                # Too wide, crop width
                new_width = int(height * desired_ratio)
                left = (width - new_width) // 2
                img = img.crop((left, 0, left + new_width, height))
            else:
                # Too tall, crop height
                new_height = int(width / desired_ratio)
                top = (height - new_height) // 2
                img = img.crop((0, top, width, top + new_height))
            
            # Resize for consistency (optional, keep high res)
            
            # 2. Add Text
            draw = ImageDraw.Draw(img)
            w, h = img.size
            
            # Font settings
            # Determine layout mode based on aspect ratio
            is_vertical = (target_w / target_h) < 1.0
            
            if is_vertical:
                # Vertical Layout (3:4) - Larger text, centered vertically
                font_size = int(w * 0.15) # 15% of width
                chars_per_line_ratio = 0.7 # Narrower column
                y_start_ratio = None # Center vertically (was 0.2)
                stroke_width = 8
            else:
                # Horizontal Layout (4:3) - Standard text, centered
                font_size = int(w * 0.11) # 11% of width (Increased from 8%)
                chars_per_line_ratio = 0.8
                y_start_ratio = None # Center vertically
                stroke_width = 7

            try:
                font = ImageFont.truetype(COVER_FONT_PATH, font_size)
            except IOError:
                logger.warning(f"Font not found at {COVER_FONT_PATH}, using default.")
                font = ImageFont.load_default()
            
            # Wrap text
            avg_char_width = font_size * 0.5
            chars_per_line = int((w * chars_per_line_ratio) / avg_char_width)
            lines = textwrap.wrap(title, width=chars_per_line)
            
            # Calculate text block height
            line_height = font_size * 1.2
            text_block_h = len(lines) * line_height
            
            # Draw position
            if y_start_ratio:
                y = int(h * y_start_ratio)
            else:
                y = (h - text_block_h) // 2
            
            # Draw semi-transparent background for text (optional but good for readability)
            # overlay = Image.new('RGBA', img.size, (0,0,0,0))
            # d = ImageDraw.Draw(overlay)
            # d.rectangle([(0, y - 20), (w, y + text_block_h + 20)], fill=(0,0,0, 100))
            # img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
            # draw = ImageDraw.Draw(img) # Re-init draw
            
            # Draw text with strong outline (better than shadow for clarity)
            for line in lines:
                text_w = draw.textlength(line, font=font)
                x = (w - text_w) // 2
                
                # Strong Outline (Stroke)
                draw.text((x, y), line, font=font, fill=(255, 255, 255), stroke_width=stroke_width, stroke_fill=(0, 0, 0))
                
                y += line_height
                
            # 3. Save
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            img.save(output_path, quality=95)
            logger.info(f"Saved cover: {output_path}")
            
    except Exception as e:
        logger.error(f"Error processing image {output_path}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Generate video covers")
    parser.add_argument("--input_file", required=True, help="Input Markdown file")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    args = parser.parse_args()
    
    input_path = Path(args.input_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Read Title and Content
    content = ""
    title = ""
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if lines:
                first_line = lines[0].strip()
                # Remove Markdown headers if present
                title = first_line.lstrip('#').strip()
                content = "".join(lines)
            
            if not title:
                title = input_path.stem
    except Exception as e:
        logger.error(f"Failed to read file: {e}")
        title = input_path.stem
        
    logger.info(f"Generating cover for title: {title}")
    
    # 2. Generate Dynamic Prompt
    prompt = generate_cover_prompt(content, title)
    
    # 3. Generate Base Image
    base_image_path = output_dir / "cover_base.png"
    if not generate_base_image(str(base_image_path), prompt):
        logger.error("Skipping cover generation due to base image failure.")
        return

    # 3. Generate 4:3 Cover
    output_filename_h = f"{input_path.stem}_horizontal.jpg"
    add_text_to_image(base_image_path, title, str(output_dir / output_filename_h), target_ratio=(4, 3))
    
    # 4. Generate 3:4 Cover
    output_filename_v = f"{input_path.stem}_vertical.jpg"
    add_text_to_image(base_image_path, title, str(output_dir / output_filename_v), target_ratio=(3, 4))
    
    # Cleanup base image
    if base_image_path.exists():
        os.remove(base_image_path)

if __name__ == "__main__":
    main()
