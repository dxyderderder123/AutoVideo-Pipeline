import json
import os
import requests
import logging
import argparse
import sys
import random
import time
import concurrent.futures
import asyncio
from pathlib import Path
from typing import List, Dict, Optional
from config import (
    PEXELS_API_KEY, PIXABAY_API_KEY, LIMIT_SEGMENTS, 
    VIDEO_SPEED_FACTOR, VIDEO_WIDTH, PROJECT_ROOT,
    MAX_DOWNLOAD_CONCURRENCY
)

# Setup logging
_log_level = os.environ.get("SELF_MEDIA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _log_level, logging.INFO), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

HISTORY_FILE = PROJECT_ROOT / "data" / "used_videos_history.json"

# Use shared locking module
try:
    from utils_lock import acquire_lock, release_lock
except ImportError:
    # Fallback if running directly without package context
    import sys
    sys.path.append(str(Path(__file__).parent))
    from utils_lock import acquire_lock, release_lock

# 尝试导入限流管理器和下载管理器
try:
    from utils_rate_limiter import rate_limiter
    _rate_limiter_available = True
except ImportError:
    _rate_limiter_available = False
    logger.warning("限流管理器不可用，使用基础请求逻辑")

try:
    from utils_downloader import get_downloader, DownloadTask
    _async_downloader_available = True
except ImportError:
    _async_downloader_available = False
    logger.warning("异步下载管理器不可用，使用同步下载")

def load_history():
    """
    Load history of used video IDs.
    Uses robust locking to ensure consistency with writers.
    """
    if not HISTORY_FILE.parent.exists():
        return set()

    lock_path = HISTORY_FILE.parent / (HISTORY_FILE.name + ".lock")
    
    # Try to acquire lock to ensure no one is writing
    # We use a shorter timeout for reading
    if acquire_lock(lock_path, timeout_seconds=10):
        try:
            if HISTORY_FILE.exists():
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    try:
                        data = json.load(f)
                        return set(data)
                    except json.JSONDecodeError:
                        return set()
            return set()
        except Exception as e:
            logger.warning(f"Failed to load history: {e}")
            return set()
        finally:
            release_lock(lock_path)
    else:
        logger.warning("Could not acquire lock to read history. Assuming empty (risky but non-blocking).")
        # Fallback: Try to read anyway if lock is held by a dead process? 
        # But acquire_lock handles stale locks. So if we failed, it's really busy.
        # Just try to read without lock as last resort
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    return set(json.load(f))
            except:
                pass
        return set()

def save_history(history_set):
    if not HISTORY_FILE.parent.exists():
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    lock_path = HISTORY_FILE.parent / (HISTORY_FILE.name + ".lock")
    
    if acquire_lock(lock_path, timeout_seconds=100):
        try:
            if not HISTORY_FILE.exists():
                with open(HISTORY_FILE, 'w') as f: f.write("[]")
            
            # Convert set to list for JSON serialization
            # Ensure all items are strings to avoid type mixing issues
            history_list = [str(x) for x in history_set]
            
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history_list, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save history: {e}")
        finally:
            release_lock(lock_path)
    else:
        logger.warning(f"Failed to acquire lock for history file after timeout. History not saved.")

def search_pexels(query, min_duration, page=1):
    """
    搜索Pexels视频
    
    优化: 使用限流管理器控制请求速率
    """
    if not PEXELS_API_KEY:
        return None
    
    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query,
        "orientation": "landscape",
        "per_page": 15,
        "page": page,
        "size": "large"
    }
    
    def _do_request():
        # 基础限流: 随机sleep 1-3s
        time.sleep(random.uniform(1.0, 3.0))
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    
    # 如果有限流管理器，使用它
    if _rate_limiter_available:
        try:
            return rate_limiter.execute("pexels", _do_request)
        except Exception as e:
            logger.error(f"Pexels API调用失败(限流控制): {e}")
            return None
    
    # 回退到原有逻辑
    for attempt in range(3):
        try:
            return _do_request()
        except Exception as e:
            logger.warning(f"Pexels API error (Attempt {attempt+1}): {e}")
            time.sleep(2)
            
    return None

def fetch_candidates_from_pool(query, required_duration, max_duration, global_used, local_used, pages_to_search=3):
    """
    POOL & PICK STRATEGY 2.0 (Pixabay Priority):
    1. Fetch first N pages from Pixabay (Primary Source).
    2. Fetch first 1 page from Pexels (Backup Source).
    3. Filter by duration and usage.
    4. Return ALL valid candidates for random selection.
    """
    pool = []
    
    try:
        min_ratio = float(os.environ.get("SELF_MEDIA_VIDEO_MIN_DURATION_RATIO", "0.3"))
    except Exception:
        min_ratio = 0.3
    min_ratio = max(0.0, min(1.0, min_ratio))
    min_seconds = max(3.0, required_duration * min_ratio)

    allow_long = os.environ.get("SELF_MEDIA_ALLOW_LONG_VIDEOS", "").strip() == "1"

    # 1. Search Pixabay (Primary - Pages 1 to N)
    if PIXABAY_API_KEY:
        for p in range(1, pages_to_search + 1):
            res = search_pixabay(query, required_duration, page=p)
            if res and 'hits' in res:
                for video in res['hits']:
                    v_id = str(video['id']) # Pixabay IDs are ints
                    # Deduplication
                    if v_id in global_used or v_id in local_used:
                        continue
                        
                    # Pixabay duration is in 'duration' field (seconds)
                    v_duration = video.get('duration', 0)
                    
                    if v_duration < min_seconds:
                        continue
                    if (not allow_long) and max_duration and v_duration > max_duration:
                        continue
                        
                    # Pixabay videos usually have a 'videos' dict with sizes
                    # We need to pick the best one (large/medium)
                    best_file = None
                    if 'videos' in video:
                        # Pixabay structure: video['videos']['large']['url']
                        # Check large then medium
                        if 'large' in video['videos'] and video['videos']['large']['width'] >= VIDEO_WIDTH:
                             best_file = video['videos']['large']
                        elif 'medium' in video['videos']:
                             best_file = video['videos']['medium']
                        elif 'large' in video['videos']:
                             best_file = video['videos']['large']
                             
                    if best_file:
                        pool.append({
                            "id": v_id,
                            "url": best_file['url'],
                            "width": best_file['width'],
                            "height": best_file['height'],
                            "duration": v_duration,
                            "source": "pixabay",
                            "page": p,
                            "tags": video.get('tags', '').lower() # Store tags for validation
                        })
            else:
                break # Stop if no results

    # 2. Search Pexels (Backup - Page 1 only)
    # Only if pool is small? Or always mix in a little? 
    # We will only use Pexels if Pixabay returned very few results (e.g. < 5)
    if PEXELS_API_KEY and len(pool) < 5:
        logger.info("Pixabay pool small, falling back to Pexels...")
        # For Pexels, we can add "tripod" to ensure stability if the query is simple
        # But for now, stick to pure query to avoid "zero results"
        res = search_pexels(query, required_duration, page=1)
        if res and 'videos' in res:
            for video in res['videos']:
                v_id = str(video['id'])
                if v_id in global_used or v_id in local_used:
                    continue
                if video['duration'] < min_seconds:
                    continue
                if (not allow_long) and max_duration and video['duration'] > max_duration:
                    continue
                best_file = get_best_video_file(video['video_files'])
                if best_file:
                    # Pexels doesn't always have 'tags' in search response, usually it's in 'url' slug
                    # We can use url slug as tags proxy
                    slug_tags = video.get('url', '').split('/')[-2].replace('-', ' ')
                    
                    pool.append({
                        "id": v_id,
                        "url": best_file['link'],
                        "width": best_file['width'],
                        "height": best_file['height'],
                        "duration": video['duration'],
                        "source": "pexels",
                        "page": 1,
                        "tags": slug_tags.lower()
                    })

    return pool

def search_pixabay(query, min_duration, page=1):
    """
    搜索Pixabay视频
    
    优化: 使用限流管理器控制请求速率
    """
    if not PIXABAY_API_KEY:
        return None
    
    url = "https://pixabay.com/api/videos/"
    params = {
        "key": PIXABAY_API_KEY,
        "q": query,
        "video_type": "film",
        "orientation": "horizontal",
        "per_page": 15,
        "page": page,
        "min_width": VIDEO_WIDTH
    }
    
    def _do_request():
        # 基础限流: 随机sleep 1-3s
        time.sleep(random.uniform(1.0, 3.0))
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    
    # 如果有限流管理器，使用它
    if _rate_limiter_available:
        try:
            return rate_limiter.execute("pixabay", _do_request)
        except Exception as e:
            logger.error(f"Pixabay API调用失败(限流控制): {e}")
            return None
    
    # 回退到原有逻辑
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Pixabay API error (Attempt {attempt+1}): {e}")
            time.sleep(2)
            
    return None

def download_video(url, output_path):
    """下载单个视频"""
    return download_video_with_fallback(url, output_path, None, 0, [])

def download_video_with_fallback(primary_url, output_path, cover_path=None, seg_id=0, fallback_urls=None):
    """
    下载视频，支持备用URL
    
    Args:
        primary_url: 主下载URL
        output_path: 输出路径
        cover_path: 封面路径(用于生成占位图)
        seg_id: segment ID
        fallback_urls: 备用URL列表
    """
    if fallback_urls is None:
        fallback_urls = []
    
    # 所有URL列表(主URL + 备用URL)
    all_urls = [primary_url] + fallback_urls
    
    output_path = Path(output_path)
    temp_path = output_path.with_suffix('.tmp')
    
    # 尝试每个URL
    for url_idx, url in enumerate(all_urls):
        url_type = "主URL" if url_idx == 0 else f"备用URL {url_idx}"
        
        # Retry configuration for each URL
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                logger.info(f"[{url_type}] 下载视频: {url[:60]}... -> {output_path.name} (尝试 {attempt+1}/{max_retries})")
                
                # Add random sleep to prevent concurrent download bursts
                time.sleep(random.uniform(0.5, 1.0))
                
                # Stream download with timeout and speed check
                start_time = time.time()
                downloaded = 0
                last_check_time = start_time
                last_downloaded = 0
                slow_speed_start = None
                
                with requests.get(url, stream=True, timeout=(10, 120)) as r:
                    r.raise_for_status()
                    with open(temp_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                current_time = time.time()
                                
                                # 每10秒检查一次下载速度
                                if current_time - last_check_time >= 10:
                                    speed_mbps = ((downloaded - last_downloaded) / (1024 * 1024)) / (current_time - last_check_time)
                                    
                                    # 检查是否慢速(低于0.3MB/s)
                                    if speed_mbps < 0.3:
                                        if slow_speed_start is None:
                                            slow_speed_start = current_time
                                            logger.warning(f"下载速度过慢: {speed_mbps:.2f}MB/s，开始计时...")
                                        elif current_time - slow_speed_start > 20:
                                            # 慢速超时，中断当前URL尝试
                                            raise TimeoutError(f"下载速度过慢({speed_mbps:.2f}MB/s)持续20秒")
                                    else:
                                        slow_speed_start = None
                                    
                                    last_check_time = current_time
                                    last_downloaded = downloaded
                
                # 下载成功，移动到最终位置
                if temp_path.exists():
                    if temp_path.stat().st_size > 0:
                        if output_path.exists():
                            output_path.unlink()
                        temp_path.replace(output_path)
                        logger.info(f"下载完成: {output_path.name} (使用{url_type})")
                        return True
                    else:
                        logger.warning(f"下载文件为空: {temp_path}")
                        temp_path.unlink()
                        
            except TimeoutError as e:
                logger.warning(f"[{url_type}] 下载超时: {e}，尝试下一个URL...")
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except:
                        pass
                break  # 跳出当前URL的重试，尝试下一个URL
                
            except Exception as e:
                logger.warning(f"[{url_type}] 下载失败 (尝试 {attempt+1}): {e}")
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except:
                        pass
                
                if attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) + random.uniform(0.1, 1.0)
                    time.sleep(sleep_time)
                else:
                    logger.warning(f"[{url_type}] 所有重试失败，尝试下一个URL...")
    
    # 所有URL都失败
    logger.error(f"所有URL都下载失败: {output_path.name}")
    return False

def get_best_video_file(video_files):
    # Sort by resolution (width * height) descending
    # Filter for mp4
    mp4_files = [v for v in video_files if v['file_type'] == 'video/mp4']
    if not mp4_files:
        return None
        
    # Sort by size
    sorted_files = sorted(mp4_files, key=lambda x: x['width'] * x['height'], reverse=True)
    
    # 2026 Optimization: Prioritize 1080p (FullHD) for efficiency
    # Try to find closest to TARGET WIDTH
    best_match = None
    min_diff = float('inf')
    
    for v in sorted_files:
        diff = abs(v['width'] - VIDEO_WIDTH)
        if diff < min_diff:
            min_diff = diff
            best_match = v
            
    if best_match:
        return best_match
            
    # Fallback to highest available if something goes wrong
    return sorted_files[0]

def fetch_videos(input_json: Path, video_output_dir: Path, output_json_path: Path = None):
    logger.info(f"Starting Video fetch. Input: {input_json}")
    
    if not input_json.exists():
        logger.error(f"Input file not found: {input_json}")
        sys.exit(1)

    with open(input_json, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not video_output_dir.exists():
        video_output_dir.mkdir(parents=True, exist_ok=True)

    segments = data.get("segments", [])
    if LIMIT_SEGMENTS:
        logger.info(f"LIMIT_SEGMENTS is set to {LIMIT_SEGMENTS}. Processing only first {LIMIT_SEGMENTS} segments.")
        segments = segments[:LIMIT_SEGMENTS]
    
    # Load history
    global_used_videos = load_history()
    used_video_ids = set() # Local set for this run to avoid dupes within same video
    
    updated_segments = []
    download_tasks = []
    reusable_video_paths = []

    fast_mode = os.environ.get("SELF_MEDIA_FAST_MODE", "").strip() == "1"
    try:
        max_downloads = int(os.environ.get("SELF_MEDIA_VIDEO_MAX_DOWNLOADS", "").strip() or "0")
    except Exception:
        max_downloads = 0
    max_downloads = max(0, max_downloads)

    try:
        download_workers = int(os.environ.get("SELF_MEDIA_VIDEO_DOWNLOAD_WORKERS", "").strip() or ("3" if fast_mode else "5"))
    except Exception:
        download_workers = 5
    download_workers = max(1, min(8, download_workers))  # 增加到最大8个并行

    # 2026 Optimization: Strict Keyword Cleanup List
    # These words confuse Pixabay/Pexels or yield generic/irrelevant results.
    BLACKLIST_TERMS = {
        "history", "story", "concept", "success", "failure", "mystery", "tips", 
        "guide", "introduction", "conclusion", "part", "chapter", "lesson",
        "culture", "society", "life", "death", "truth", "myth", "legend",
        "psychology", "mind", "thought", "idea", "plan", "strategy",
        "cinematic", "close up", "slow motion", "4k", "hd", "background",
        "view", "shot", "scene", "video", "footage", "clip"
    }

    for seg in segments:
        seg_id = seg.get("id")
        keywords = seg.get("video_keywords", [])
        duration = seg.get("duration", 10) # Default to 10s if missing
        
        # 2026 Fix (Quota Saver): Ensure no single segment downloads too many videos!
        # Max 2 shots per 20s segment, reducing API costs dramatically.
        shots_needed = max(1, min(2, int(duration // 10.0)))
        shot_duration = duration / shots_needed
        
        # Adjust required duration for speed factor
        required_duration = shot_duration * VIDEO_SPEED_FACTOR
        max_duration = required_duration * 2.5  # More lenient cap for short shots
        if max_duration > 45: max_duration = 45 

        # 如果全局下载量已经达到上限，立刻停止搜索并复用
        if max_downloads and len(download_tasks) >= max_downloads and reusable_video_paths:
            logger.info(f"Segment {seg_id}: Global download limit ({max_downloads}) reached. Reusing local video.")
            seg_video_files = []
            for _ in range(shots_needed):
                reuse_path = random.choice(reusable_video_paths)
                seg_video_files.append(str(reuse_path))
            
            seg['video_files'] = seg_video_files
            seg['video_file'] = seg_video_files[0]
            updated_segments.append(seg)
            continue
        
        # Clean keywords to ensure no sentences
        cleaned_keywords = []
        for k in keywords:
            k_lower = k.lower().strip()
            if k_lower in BLACKLIST_TERMS:
                continue
            words = k.split()
            if len(words) > 3:
                cleaned_keywords.append(" ".join(words[:2]))
            else:
                cleaned_keywords.append(k)

        search_candidates = cleaned_keywords[:3]
        if not search_candidates:
             search_candidates = ["nature"] # Ultimate fallback
             
        logger.info(f"Segment {seg_id} ({duration:.1f}s, needs {shots_needed} shots): Candidates: {search_candidates}")

        chosen_videos = []
        all_valid_candidates = []
        
        # 1. 尽量让不同的关键词各贡献一个镜头
        for query_idx, query in enumerate(search_candidates):
            logger.info(f"Searching attempt {query_idx+1}/{len(search_candidates)}: '{query}'")
            all_candidates = fetch_candidates_from_pool(query, required_duration, max_duration, global_used_videos, used_video_ids, pages_to_search=3)
            
            valid_candidates = []
            query_words = set(query.lower().split())
            
            for cand in all_candidates:
                tags = cand.get('tags', '')
                is_relevant = False
                if query == "nature":
                    is_relevant = True
                else:
                    for qw in query_words:
                        if qw in tags:
                            is_relevant = True
                            break
                if is_relevant:
                    valid_candidates.append(cand)
            
            if not valid_candidates:
                if all_candidates:
                    valid_candidates = all_candidates
                else:
                    continue
            
            random.shuffle(valid_candidates)
            all_valid_candidates.extend(valid_candidates)
            
            # 从这个关键词结果中挑一个最好的
            perfect_matches = [c for c in valid_candidates if required_duration <= c['duration'] <= max_duration]
            if perfect_matches:
                chosen_videos.append(perfect_matches[0])
            else:
                chosen_videos.append(valid_candidates[0])
                
            if len(chosen_videos) >= shots_needed:
                break

        # 2. 如果镜头不够，从之前收集的所有候选中补充
        if len(chosen_videos) < shots_needed and all_valid_candidates:
            used_ids_in_seg = {v['id'] for v in chosen_videos}
            remaining = [v for v in all_valid_candidates if v['id'] not in used_ids_in_seg]
            
            # 优先用 perfect matches
            perfect = [c for c in remaining if required_duration <= c['duration'] <= max_duration]
            random.shuffle(perfect)
            
            needed = shots_needed - len(chosen_videos)
            added = 0
            for v in perfect:
                if added >= needed: break
                chosen_videos.append(v)
                used_ids_in_seg.add(v['id'])
                added += 1
                
            # 如果还是不够
            if len(chosen_videos) < shots_needed:
                others = [c for c in remaining if c['id'] not in used_ids_in_seg]
                random.shuffle(others)
                needed = shots_needed - len(chosen_videos)
                chosen_videos.extend(others[:needed])

        # 3. 如果依然不够，使用 nature 后备
        if len(chosen_videos) < shots_needed:
            logger.warning(f"Segment {seg_id} still needs shots. Falling back to 'nature'.")
            fallback_cands = fetch_candidates_from_pool("nature", required_duration, max_duration, global_used_videos, used_video_ids, pages_to_search=1)
            if fallback_cands:
                used_ids_in_seg = {v['id'] for v in chosen_videos}
                remaining = [v for v in fallback_cands if v['id'] not in used_ids_in_seg]
                random.shuffle(remaining)
                needed = shots_needed - len(chosen_videos)
                chosen_videos.extend(remaining[:needed])

        if chosen_videos:
            seg_video_files = []
            
            for shot_idx, found_video in enumerate(chosen_videos):
                # Apply Max Downloads check PER shot creation
                if max_downloads and len(download_tasks) >= max_downloads and reusable_video_paths:
                    reuse_path = random.choice(reusable_video_paths)
                    seg_video_files.append(str(reuse_path))
                    logger.info(f"Segment {seg_id} Shot {shot_idx}: Reached max_downloads! Reusing existing video.")
                    continue
            
                # Mark as used globally and locally
                used_video_ids.add(found_video['id'])
                global_used_videos.add(found_video['id'])
                
                output_filename = f"{seg_id}_{shot_idx}_{found_video['id']}.mp4"
                output_path = video_output_dir / output_filename
                
                # 记录要下载的任务（这里简化 fallback URL）
                download_tasks.append({
                    'seg_id': seg_id,
                    'primary_url': found_video['url'],
                    'fallback_urls': [], 
                    'output_path': output_path
                })
                seg_video_files.append(str(output_path))
                reusable_video_paths.append(output_path)
            
            # 兼容性：同时保存列表与单个（首个）元素
            seg['video_files'] = seg_video_files
            seg['video_file'] = seg_video_files[0]
            updated_segments.append(seg)
        else:
            logger.warning(f"FAILED to find ANY video for segment {seg_id}")
            seg['video_files'] = []
            updated_segments.append(seg)
            
    # Save updated global history
    save_history(global_used_videos)

    # Download videos in parallel
    logger.info(f"Downloading {len(download_tasks)} videos...")
    
    # 优化: 使用异步下载管理器(如果可用)
    if _async_downloader_available and len(download_tasks) > 1:
        logger.info("使用异步下载管理器进行并发下载")
        try:
            # 获取下载器实例
            downloader = get_downloader()
            
            # 创建下载任务
            async_tasks = []
            for url, output_path in download_tasks:
                task = DownloadTask(url=url, output_path=output_path)
                async_tasks.append(task)
            
            # 执行异步下载
            results = asyncio.run(downloader.download_many(async_tasks))
            
            # 处理结果 - 检查失败的任务并使用占位图
            failed_tasks = []
            for i, result in enumerate(results):
                if not result.success:
                    failed_tasks.append((i, async_tasks[i]))
            
            if failed_tasks:
                logger.warning(f"异步下载失败 {len(failed_tasks)} 个")
                for idx, task in failed_tasks:
                    logger.warning(f"下载失败: {task.output_path.name}")
            
            success_count = sum(1 for r in results if r.success)
            logger.info(f"异步下载完成: {success_count}/{len(results)} 成功")
            
        except Exception as e:
            logger.warning(f"异步下载失败，回退到同步下载: {e}")
            # 回退到同步下载
            with concurrent.futures.ThreadPoolExecutor(max_workers=download_workers) as executor:
                futures = {}
                for i, task_info in enumerate(download_tasks):
                    if isinstance(task_info, dict):
                        future = executor.submit(
                            download_video_with_fallback,
                            task_info['primary_url'],
                            task_info['output_path'],
                            None,  # cover_path
                            task_info.get('seg_id', 0),
                            task_info.get('fallback_urls', [])
                        )
                        futures[future] = task_info['output_path']
                    else:
                        url, path = task_info
                        future = executor.submit(download_video, url, path)
                        futures[future] = path
                
                for future in concurrent.futures.as_completed(futures):
                    path = futures[future]
                    try:
                        success = future.result()
                        if success:
                            logger.info(f"Downloaded video: {path}")
                        else:
                            logger.warning(f"Failed to download video: {path}")
                    except Exception as e:
                        logger.error(f"Download exception for {path}: {e}")
    else:
        # 使用原有的同步下载，支持备用URL
        with concurrent.futures.ThreadPoolExecutor(max_workers=download_workers) as executor:
            futures = {}
            for task_info in download_tasks:
                if isinstance(task_info, dict):
                    # 新的任务格式，支持备用URL
                    future = executor.submit(
                        download_video_with_fallback,
                        task_info['primary_url'],
                        task_info['output_path'],
                        None,  # cover_path
                        task_info.get('seg_id', 0),
                        task_info.get('fallback_urls', [])
                    )
                    futures[future] = task_info['output_path']
                else:
                    # 旧的任务格式 (url, path) 元组
                    url, path = task_info
                    future = executor.submit(download_video, url, path)
                    futures[future] = path
            
            for future in concurrent.futures.as_completed(futures):
                path = futures[future]
                try:
                    success = future.result()
                    if success:
                        logger.info(f"Downloaded video: {path}")
                    else:
                        logger.warning(f"Failed to download video: {path}")
                except Exception as e:
                    logger.error(f"Download exception for {path}: {e}")

    # Save updated JSON
    if output_json_path is None:
        output_json_path = input_json.parent / "analysis_video.json"
        
    data["segments"] = updated_segments
    
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Video fetch complete. Updated data saved to {output_json_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_json", type=Path, help="Path to analysis_tts.json")
    parser.add_argument("--output_dir", type=Path, help="Directory to save video files")
    parser.add_argument("--output_json", type=Path, default=None, help="Optional path for output JSON")
    args = parser.parse_args()
    
    if args.input_json and args.output_dir:
        fetch_videos(args.input_json, args.output_dir, args.output_json)
