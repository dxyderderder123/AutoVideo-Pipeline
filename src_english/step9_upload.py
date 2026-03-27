import asyncio
import argparse
import os
import sys
import logging
import json
import traceback
import time
import requests
from pathlib import Path
from bilibili_api import Credential, sync
from bilibili_api.utils.network import Api
from bilibili_api.video_uploader import VideoUploader, VideoUploaderPage, VideoMeta
from bilibili_api.video import Video

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))
from config import (
    ENABLE_UPLOAD, BILIBILI_SESSDATA, BILIBILI_BILI_JCT, 
    BILIBILI_BUVID3, BILIBILI_TAGS, BILIBILI_DEDEUSERID,
    BILIBILI_COLLECTION_RULES, TEMP_BASE_DIR
)

# 使用TEMP_BASE_DIR作为锁文件目录
CACHE_DIR = TEMP_BASE_DIR

# Use shared locking module
try:
    from utils_lock import acquire_lock, release_lock
except ImportError:
    # Fallback if running directly without package context
    import sys
    sys.path.append(str(Path(__file__).parent))
    from utils_lock import acquire_lock, release_lock

# Configure logging
_log_level = os.environ.get("SELF_MEDIA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _log_level, logging.INFO), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def add_video_to_collection(aid: int, title: str, source_filename: str, credential: Credential, metadata_line: str = "", bvid: str = ""):
    """
    Check rules and add video to collection (Season/Series).
    Priority: 
    1. Check source_filename
    2. Check metadata_line (Difficulty level from file content)
    3. Check title
    """
    if not BILIBILI_COLLECTION_RULES:
        logger.info("No collection rules defined in config. Skipping collection add.")
        return

    target_collection_id = None
    
    # 1. Check filename first (Priority 1)
    for keyword, col_id in BILIBILI_COLLECTION_RULES.items():
        if keyword.lower() in source_filename.lower():
            target_collection_id = col_id
            logger.info(f"Matched collection rule (Filename): '{keyword}' -> ID {col_id}")
            break
            
    # 2. Check metadata_line (Priority 2)
    # Metadata line format example: "难度：四级单词：436读后感：36"
    if not target_collection_id and metadata_line:
        # Flexible mapping for various difficulty keywords
        # The key is the substring to look for in metadata_line
        # The value is the key in BILIBILI_COLLECTION_RULES ("1初阶", etc.)
        difficulty_map = {
            # 1初阶 (高考)
            "高考": "1初阶",
            
            # 2中阶 (四级)
            "四级": "2中阶",
            
            # 3中高阶 (六级/考研)
            "六级": "3中高阶",
            "考研": "3中高阶",
            
            # 4高阶 (雅思/托福/专四)
            "雅思": "4高阶",
            "托福": "4高阶",
            "专四": "4高阶",
            
            # 5精通 (SAT/专八/GRE)
            "SAT": "5精通",
            "专八": "5精通",
            "GRE": "5精通"
        }
        
        # Iterate and find the first match
        for diff_keyword, rule_key in difficulty_map.items():
            if diff_keyword in metadata_line:
                # Find the ID for the mapped rule_key
                if rule_key in BILIBILI_COLLECTION_RULES:
                    target_collection_id = BILIBILI_COLLECTION_RULES[rule_key]
                    logger.info(f"Matched collection rule (Metadata: '{diff_keyword}'): '{rule_key}' -> ID {target_collection_id}")
                    break
        
    # 3. Fallback to title check (Priority 3)
    if not target_collection_id:
        for keyword, col_id in BILIBILI_COLLECTION_RULES.items():
            if keyword.lower() in title.lower():
                target_collection_id = col_id
                logger.info(f"Matched collection rule (Title): '{keyword}' -> ID {col_id}")
                break
            
    if not target_collection_id:
        logger.info(f"No matching collection rule found for video (File: {source_filename}, Title: {title}).")
        return

    # Add to collection API call
    # Strategy:
    # 1. Try channel_series (Video List) - Might fail if it's a "Season"
    # 2. Try Season/Section (New Collection) - Robust fallback
    
    from bilibili_api import channel_series
    
    # Attempt 1: channel_series (Series/Video List)
    logger.info(f"Adding video (aid: {aid}) to collection {target_collection_id} (Attempt 1: channel_series)...")
    try:
        resp = await channel_series.add_aids_to_series(
            series_id=target_collection_id,
            aids=[aid],
            credential=credential
        )
        logger.info(f"✅ Successfully added to Series! Response: {resp}")
        return
    except Exception as e:
        logger.warning(f"Attempt 1 (Series) failed: {e}. Switching to Attempt 2 (Season)...")
        logger.debug(traceback.format_exc())

    # Attempt 2: Season/Section (New Collection)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"https://member.bilibili.com/platform/upload/video/frame?type=edit&bvid={bvid}" if bvid else "https://member.bilibili.com/platform/upload/video/frame",
        "Origin": "https://member.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8"
    }
    cookies = {
        "SESSDATA": BILIBILI_SESSDATA,
        "bili_jct": BILIBILI_BILI_JCT,
        "buvid3": BILIBILI_BUVID3,
        "DedeUserID": BILIBILI_DEDEUSERID
    }

    try:
        cid = None

        if bvid:
            try:
                view_resp = requests.get(
                    "https://member.bilibili.com/x/vupre/web/archive/view",
                    params={"topic_grey": 1, "bvid": bvid},
                    headers=headers,
                    cookies=cookies,
                    timeout=15
                )
                view_resp.raise_for_status()
                view_json = view_resp.json()
                if view_json.get("code") == 0:
                    view_data = view_json.get("data") or {}
                    arc = view_data.get("archive") or {}
                    state = arc.get("state")
                    state_desc = arc.get("state_desc")
                    if state == -100 or (isinstance(state_desc, str) and "已删除" in state_desc):
                        logger.error(f"Archive is deleted/locked. Cannot add to collection. bvid={bvid} aid={aid} state={state} state_desc={state_desc}")
                        return
                    videos = view_data.get("videos") or []
                    if videos:
                        cid = videos[0].get("cid")
            except Exception as e:
                logger.warning(f"archive/view probe failed: {e}")

        if not cid:
            v = Video(aid=aid, credential=credential)
            backoff_seconds = [2, 3, 5, 8, 13, 21]
            for attempt, delay in enumerate(backoff_seconds, start=1):
                try:
                    pages = await v.get_pages()
                    if pages:
                        cid = pages[0].get("cid")
                    if cid:
                        break
                    logger.warning(f"CID not ready yet (attempt {attempt}/{len(backoff_seconds)}). Retrying in {delay}s...")
                except Exception as e:
                    logger.warning(f"Failed to fetch CID (attempt {attempt}/{len(backoff_seconds)}): {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)

        if not cid:
            logger.error(f"Could not fetch CID after retries for aid={aid}. Skipping season add.")
            return

        seasons_resp = requests.get(
            "https://member.bilibili.com/x2/creative/web/seasons",
            params={"pn": 1, "ps": 100},
            headers=headers,
            cookies=cookies,
            timeout=15
        )
        seasons_resp.raise_for_status()
        seasons_json = seasons_resp.json()
        seasons = seasons_json.get("data", {}).get("seasons", [])
        season_item = next((x for x in seasons if x.get("season", {}).get("id") == target_collection_id), None)
        if not season_item:
            logger.error(f"Season not found in creator list. season_id={target_collection_id}")
            return

        sections = season_item.get("sections", {}).get("sections", [])
        if not sections:
            logger.error(f"No sections found for season_id={target_collection_id}")
            return
        section_id = sections[0].get("id")
        if not section_id:
            logger.error(f"Invalid section_id for season_id={target_collection_id}")
            return

        logger.info(f"Adding AID {aid} to Season {target_collection_id} (section_id={section_id})...")
        add_resp = requests.post(
            "https://member.bilibili.com/x2/creative/web/season/section/episodes/add",
            params={"t": int(time.time() * 1000), "csrf": BILIBILI_BILI_JCT},
            json={
                "sectionId": int(section_id),
                "episodes": [{"title": title, "cid": int(cid), "aid": int(aid)}],
                "csrf": BILIBILI_BILI_JCT,
            },
            headers=headers,
            cookies=cookies,
            timeout=15
        )
        add_resp.raise_for_status()
        add_json = add_resp.json()
        if add_json.get("code") == 20080:
            logger.info("Video already exists in collection. Verifying...")
        elif add_json.get("code") != 0:
            logger.error(f"Season add failed: {add_json}")
            return

        verified = False
        for attempt in range(1, 6):
            verify_resp = requests.get(
                "https://member.bilibili.com/x2/creative/web/seasons",
                params={"pn": 1, "ps": 100},
                headers=headers,
                cookies=cookies,
                timeout=15
            )
            verify_resp.raise_for_status()
            verify_json = verify_resp.json()
            verify_seasons = verify_json.get("data", {}).get("seasons", [])
            verify_item = next((x for x in verify_seasons if x.get("season", {}).get("id") == target_collection_id), None)
            if not verify_item:
                logger.error(f"Season disappeared after add. season_id={target_collection_id}")
                return
            episodes = verify_item.get("part_episodes", []) or []
            if any(int(ep.get("aid", 0)) == int(aid) for ep in episodes):
                verified = True
                break
            await asyncio.sleep(1.5)

        if verified:
            logger.info("✅ Verified: video is in collection.")
        else:
            logger.error(f"Add returned code=0 but verify not found. aid={aid} season_id={target_collection_id}")

        return
    except Exception as e:
        logger.error(f"Attempt 2 (Season) failed: {e}")
        logger.debug(traceback.format_exc())
        return

async def upload_video_to_bilibili(video_path: Path, cover_path: Path, title: str, desc: str, tags: list, source_filename: str = "", metadata_line: str = ""):
    """
    Upload video to Bilibili using the official API wrapper (bilibili-api-python).
    """
    if not ENABLE_UPLOAD:
        logger.info("Upload is disabled in config.py. Skipping.")
        return

    # 1. Validate Credentials
    if not all([BILIBILI_SESSDATA, BILIBILI_BILI_JCT, BILIBILI_BUVID3]):
        logger.error("Missing Bilibili credentials (SESSDATA, BILI_JCT, BUVID3). Please check your .env file.")
        return

    credential = Credential(
        sessdata=BILIBILI_SESSDATA,
        bili_jct=BILIBILI_BILI_JCT,
        buvid3=BILIBILI_BUVID3,
        dedeuserid=BILIBILI_DEDEUSERID
    )

    # --- WAF Bypass Patch Start ---
    # Inject full RAW cookie into Credential to bypass Bilibili 406 Not Acceptable WAF error
    raw_cookie = os.getenv("BILIBILI_RAW_COOKIE", "")
    if raw_cookie:
        cookie_dict = {}
        for item in raw_cookie.split(';'):
            if '=' in item:
                k, v = item.strip().split('=', 1)
                cookie_dict[k] = v
        # Ensure base cookies are not missing if raw_cookie is incomplete
        if BILIBILI_SESSDATA: cookie_dict['SESSDATA'] = BILIBILI_SESSDATA
        if BILIBILI_BILI_JCT: cookie_dict['bili_jct'] = BILIBILI_BILI_JCT
        if BILIBILI_DEDEUSERID: cookie_dict['DedeUserID'] = BILIBILI_DEDEUSERID
        
        async def custom_get_cookies():
            return cookie_dict
            
        credential.get_cookies = custom_get_cookies
        credential.get_buvid_cookies = custom_get_cookies
        logger.info("✅ Injected Full Browser Raw Cookies for WAF bypass.")
        
        # Patch User-Agent to match Windows Chrome (the one that generated the cookies)
        from bilibili_api.utils.network import get_client
        client = get_client()
        if not hasattr(client, '_is_patched'):
            orig_req = client.request
            async def patched_req(method, url, **kwargs):
                if 'headers' in kwargs and kwargs['headers']:
                    kwargs['headers']['User-Agent'] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                return await orig_req(method, url, **kwargs)
            client.request = patched_req
            client._is_patched = True
            logger.info("✅ Injected User-Agent Spoofing for WAF bypass.")
    # --- WAF Bypass Patch End ---

    # 2. Validate Files
    if not video_path.exists():
        logger.error(f"Video file not found: {video_path}")
        return
    
    # 3. Prepare Upload Objects
    logger.info(f"Starting upload for: {title} (Source: {source_filename})")
    
    # Page (Video File)
    # Description: Use minimal description if desc is empty or "Generated by..."
    # User requested NO description, but Bilibili might require something.
    # Let's use the title or a simple space if allowed. 
    # Actually, let's use the title as description if desc is not provided or is default.
    final_desc = desc
    if not final_desc or "Generated by" in final_desc:
        final_desc = title  # Fallback to title as description
    
    page = VideoUploaderPage(path=str(video_path), title=title, description=final_desc)
    
    # Meta (Video Info)
    # TID 208 = Knowledge -> Campus Learning (Appropriate for English learning/Education)
    # Previous: TID 154 (Dance - Incorrect), 231 (Tech)
    meta = VideoMeta(
        title=title,
        desc=final_desc,
        cover=str(cover_path) if cover_path and cover_path.exists() else "",
        tid=208, 
        tags=tags
    )
    
    # Uploader
    uploader = VideoUploader(
        pages=[page],
        meta=meta,
        credential=credential
    )

    try:
        # 4. Start Upload
        logger.info("Uploading video and metadata...")
        
        # 2026 Fix: Add retry mechanism for video upload (Network instability protection)
        max_upload_retries = 3
        res = None
        
        for attempt in range(max_upload_retries):
            try:
                if attempt > 0:
                    logger.info(f"Retrying upload (Attempt {attempt+1}/{max_upload_retries})...")
                    await asyncio.sleep(5) # Wait before retry
                    
                res = await uploader.start()
                logger.info(f"Upload successful! Result: {res}")
                break # Success
            except Exception as e:
                logger.error(f"Upload failed (Attempt {attempt+1}): {e}")
                if attempt == max_upload_retries - 1:
                    raise e # Re-raise on final failure
        
        # 5. Add to Collection (if rules match)
        # Bilibili API logic for adding to collection/season
        # The return value of uploader.start() usually contains 'aid' and 'bvid'.
        
        aid = None
        bvid = None
        if isinstance(res, dict):
             if 'aid' in res:
                 aid = res['aid']
             elif 'data' in res and 'aid' in res['data']:
                 aid = res['data']['aid']
             if 'bvid' in res:
                 bvid = res['bvid']
             elif 'data' in res and 'bvid' in res['data']:
                 bvid = res['data']['bvid']
        
        if not aid:
            # Fallback: bvid to aid if needed, but usually response has aid
            logger.warning(f"Could not find AID in upload response: {res}. Skipping collection add.")
            return

        # Wait a bit before adding to collection to ensure backend consistency
        await asyncio.sleep(2.0)
        await add_video_to_collection(aid, title, source_filename, credential, metadata_line, bvid or "")
        
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Upload Video to Bilibili")
    parser.add_argument("--video_path", required=True, help="Path to the final video file (.mp4)")
    parser.add_argument("--cover_path", required=True, help="Path to the cover image")
    parser.add_argument("--title_file", required=True, help="Path to the original text file (for title)")
    parser.add_argument("--desc", default="Generated by AI Agent", help="Video description")
    
    args = parser.parse_args()
    
    video_path = Path(args.video_path)
    cover_path = Path(args.cover_path)
    title_file = Path(args.title_file)
    
    # Extract Title (First line of input file)
    # And Metadata if available
    metadata_line = ""
    if title_file.exists():
        try:
            with open(title_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # Find first non-empty line
                title = "Untitled Video"
                if lines:
                    title = lines[0].strip()[:80] # Bilibili limit 80 chars
                    
                    # Flexible metadata extraction (check first 5 lines)
                    for line in lines[:5]:
                        if "难度：" in line or "单词：" in line:
                            metadata_line = line.strip()
                            break
                    if metadata_line:
                        logger.info(f"Read metadata line: {metadata_line}")
        except Exception as e:
            logger.warning(f"Could not read title file: {e}")
            title = "AI Generated Video"
    else:
        title = "AI Generated Video"
        
    logger.info(f"Extracted Title: {title}")
    
    # Get Source Filename Stem
    source_filename = title_file.stem
    logger.info(f"Source Filename Stem: {source_filename}")

    # Load dynamic tags from analysis.json if available
    dynamic_tags = []
    # Check parent/parent for analysis file (assuming video is in temp/output/final.mp4)
    analysis_json_path = video_path.parent.parent / "analysis_merged.json"
    if not analysis_json_path.exists():
        analysis_json_path = video_path.parent.parent / "analysis.json"
        
    if analysis_json_path.exists():
        try:
            with open(analysis_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "tags" in data and isinstance(data["tags"], list):
                    dynamic_tags = data["tags"][:5] # Max 5 tags
                    logger.info(f"Loaded dynamic tags from {analysis_json_path}: {dynamic_tags}")
        except Exception as e:
            logger.warning(f"Failed to load dynamic tags: {e}")
            
    final_tags = dynamic_tags if dynamic_tags else BILIBILI_TAGS

    # Run Async Upload
    # Global Upload Lock (Industrial Grade Serialization)
    # Prevents Bilibili API rate limits and network congestion
    upload_lock_path = CACHE_DIR / "upload.lock"
    
    logger.info("Requesting upload lock (serialized upload)...")
    # Wait up to 1 hour for upload lock
    if acquire_lock(upload_lock_path, timeout_seconds=3600, stale_threshold=600):
        try:
            sync(upload_video_to_bilibili(
                video_path=video_path,
                cover_path=cover_path,
                title=title,
                desc=args.desc,
                tags=final_tags,
                source_filename=source_filename,
                metadata_line=metadata_line
            ))
        finally:
            release_lock(upload_lock_path)
            logger.info("Released upload lock.")
    else:
        logger.error("Failed to acquire upload lock after timeout. Upload skipped.")
        sys.exit(1)

if __name__ == "__main__":
    main()
