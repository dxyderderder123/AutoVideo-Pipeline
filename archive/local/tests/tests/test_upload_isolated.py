import asyncio
import os
import sys
import logging
from pathlib import Path

# Mock project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "src_english"))

# Import config (will try to load .env)
try:
    from config import BILIBILI_SESSDATA, BILIBILI_BILI_JCT, BILIBILI_BUVID3, BILIBILI_DEDEUSERID
except ImportError:
    print("Error importing config. Make sure src_english is in python path.")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestUpload")

async def test_credentials():
    print("-" * 50)
    print("Testing Bilibili Credentials...")
    
    # 1. Check if variables are loaded
    if not all([BILIBILI_SESSDATA, BILIBILI_BILI_JCT, BILIBILI_BUVID3]):
        logger.error("MISSING CREDENTIALS in .env or config!")
        print(f"SESSDATA: {'Set' if BILIBILI_SESSDATA else 'Missing'}")
        print(f"BILI_JCT: {'Set' if BILIBILI_BILI_JCT else 'Missing'}")
        print(f"BUVID3:   {'Set' if BILIBILI_BUVID3 else 'Missing'}")
        return False
        
    logger.info("Credentials found in config.")
    
    # 2. Test Login Status via bilibili_api
    try:
        from bilibili_api import Credential, user, sync
        
        credential = Credential(
            sessdata=BILIBILI_SESSDATA,
            bili_jct=BILIBILI_BILI_JCT,
            buvid3=BILIBILI_BUVID3,
            dedeuserid=BILIBILI_DEDEUSERID
        )
        
        # Get self info
        logger.info("Verifying login status with API...")
        me = user.User(uid=int(BILIBILI_DEDEUSERID) if BILIBILI_DEDEUSERID else 0, credential=credential)
        info = await me.get_user_info()
        
        print(f"Login Successful! User: {info['name']} (Level {info['level']})")
        return True
        
    except Exception as e:
        logger.error(f"Login Check Failed: {e}")
        return False

async def main():
    success = await test_credentials()
    if not success:
        print("Upload will fail because credentials are invalid.")
        sys.exit(1)
    else:
        print("Credentials valid. Upload script logic looks okay.")

if __name__ == "__main__":
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
