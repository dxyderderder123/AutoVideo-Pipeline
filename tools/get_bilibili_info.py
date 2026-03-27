import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from bilibili_api import Credential, user, sync

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))
try:
    from src_english.config import PROJECT_ROOT
except ImportError:
    pass

def load_credentials():
    load_dotenv()
    sessdata = os.getenv("BILIBILI_SESSDATA")
    bili_jct = os.getenv("BILIBILI_BILI_JCT")
    buvid3 = os.getenv("BILIBILI_BUVID3")
    dedeuserid = os.getenv("BILIBILI_DEDEUSERID")

    if not sessdata or not bili_jct:
        print("Error: BILIBILI_SESSDATA and BILIBILI_BILI_JCT must be set in .env file or environment variables.")
        print("Please create a .env file in the project root with the following content:")
        print("BILIBILI_SESSDATA=your_sessdata")
        print("BILIBILI_BILI_JCT=your_bili_jct")
        print("BILIBILI_BUVID3=your_buvid3")
        print("BILIBILI_DEDEUSERID=your_uid")
        return None, None

    return Credential(sessdata=sessdata, bili_jct=bili_jct, buvid3=buvid3, dedeuserid=dedeuserid), dedeuserid

async def main():
    print("Fetching Bilibili User Info...")
    credential, uid = load_credentials()
    if not credential:
        return

    try:
        # 1. Get User Info
        if not uid:
            print("UID not found in env, attempting to fetch self info...")
            my_info = await user.get_self_info(credential)
            uid = my_info['mid']
            print(f"Detected UID: {uid}")
        
        u = user.User(uid, credential=credential)
        info = await u.get_user_info()
        print(f"\nUser: {info['name']} (Level {info['level']})")
        
        # 2. Get Collections (Seasons/Series)
        print("\nFetching Collections (Seasons/Series)...")
        channels = await u.get_channels()
        
        if not channels:
            print("No collections found.")
        else:
            print(f"Found {len(channels)} collections:")
            print("-" * 50)
            print(f"{'ID':<15} | {'Type':<10} | {'Name'}")
            print("-" * 50)
            for ch in channels:
                meta = await ch.get_meta()
                # meta structure varies between season and series
                # Series: {'series_id': 123, 'name': 'xxx', ...}
                # Season: {'season_id': 123, 'title': 'xxx', ...} or from 'meta' dict
                
                c_type = ch.get_type().name
                c_id = ch.get_id()
                c_name = meta.get('name') or meta.get('title') or "Unknown"
                
                print(f"{c_id:<15} | {c_type:<10} | {c_name}")
            print("-" * 50)
            
        print("\n[Usage Hint]")
        print("Copy the ID of the collection you want to use and update 'BILIBILI_COLLECTION_MAP' in src_english/config.py")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    sync(main())
