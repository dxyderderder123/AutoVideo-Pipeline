import json
import subprocess
import sys
from pathlib import Path
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock config
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT / "src_english"))

# Import the merge logic (we'll invoke it as a subprocess or import function)
# Ideally import to test the exact code
try:
    from step7_merge import merge_all
except ImportError:
    logger.error("Could not import step7_merge. Make sure src_english is in path.")
    sys.exit(1)

def create_dummy_video(path, duration, color):
    """Create a dummy video with silence audio"""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c={color}:s=1920x1080:d={duration}",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration}",
        "-c:v", "libx264", "-c:a", "aac", 
        str(path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def test_merge_logic():
    test_dir = Path("tests/temp_merge_test")
    test_dir.mkdir(parents=True, exist_ok=True)
    
    output_dir = test_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Create dummy assets
    vid1 = test_dir / "vid1.mp4"
    vid2 = test_dir / "vid2.mp4"
    create_dummy_video(vid1, 2.0, "red")
    create_dummy_video(vid2, 2.0, "blue")
    
    # 2. Create input JSON
    analysis_data = {
        "segments": [
            {
                "id": 1,
                "video_file": str(vid1),
                "audio_file": None, # Will use silence
                "duration": 2.0
            },
            {
                "id": 2,
                "video_file": str(vid2),
                "audio_file": None,
                "duration": 2.0
            }
        ]
    }
    
    input_json = test_dir / "analysis.json"
    with open(input_json, "w") as f:
        json.dump(analysis_data, f)
        
    # 3. Run merge
    logger.info("Running merge_all...")
    try:
        # We assume END_NOTE_ENABLE is True in config, but we can't easily change imported config constants
        # So we just check if it merges the main videos correctly.
        # If END_NOTE is enabled, total duration should be 2+2+3 = 7s.
        # If disabled, 4s.
        # But the bug is that it produced ONLY 3s (End note only).
        
        merge_all(input_json, output_dir, "test_video")
        
        final_video = output_dir / "final_video.mp4"
        if not final_video.exists():
            logger.error("Final video not created!")
            sys.exit(1)
            
        # Check duration
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(final_video)],
            capture_output=True, text=True
        )
        duration = float(result.stdout.strip())
        logger.info(f"Final video duration: {duration} seconds")
        
        if duration < 3.5:
            logger.error("FAIL: Duration too short. Likely only end note was rendered.")
            sys.exit(1)
        else:
            logger.info("PASS: Duration looks correct (expected > 4s).")
            
    except Exception as e:
        logger.error(f"Test failed with exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_merge_logic()
