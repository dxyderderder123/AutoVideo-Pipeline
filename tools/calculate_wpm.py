import json
import os
from pathlib import Path
import numpy as np
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def calculate_wpm(workspace_dir):
    temp_dir = Path(workspace_dir) / "temp"
    if not temp_dir.exists():
        logger.error(f"Temp directory not found: {temp_dir}")
        return

    total_words = 0
    total_duration = 0.0
    segment_wpms = []
    
    logger.info(f"Scanning {temp_dir} for analysis_tts.json...")
    
    json_files = list(temp_dir.glob("*/analysis_tts.json"))
    if not json_files:
        logger.warning("No analysis_tts.json files found. Checking analysis.json with 'audio_file'...")
        json_files = list(temp_dir.glob("*/analysis.json"))
        
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            segments = data.get("segments", [])
            for seg in segments:
                text = seg.get("text", "").strip()
                duration = seg.get("duration", 0.0)
                
                # Only consider valid segments with actual TTS duration
                # Check if audio_file exists to be sure it's real
                audio_file = seg.get("audio_file")
                if not audio_file or not duration or duration < 0.1:
                    continue
                    
                word_count = len(text.split())
                if word_count == 0:
                    continue
                    
                wpm = (word_count / duration) * 60
                
                # Filter outliers (e.g. extremely fast or slow due to errors)
                if wpm < 50 or wpm > 300:
                    continue
                    
                segment_wpms.append(wpm)
                total_words += word_count
                total_duration += duration
                
        except Exception as e:
            logger.warning(f"Error reading {json_file}: {e}")

    if not segment_wpms:
        logger.error("No valid TTS data found to calculate WPM.")
        return

    avg_wpm = np.mean(segment_wpms)
    median_wpm = np.median(segment_wpms)
    std_dev = np.std(segment_wpms)
    min_wpm = np.min(segment_wpms)
    max_wpm = np.max(segment_wpms)
    
    # Calculate Seconds Per Word (SPW)
    avg_spw = 60 / avg_wpm if avg_wpm > 0 else 0
    slowest_spw = 60 / (avg_wpm - 2 * std_dev) if (avg_wpm - 2 * std_dev) > 0 else 1.0
    
    logger.info("-" * 40)
    logger.info(f"TTS Statistics (Based on {len(segment_wpms)} segments)")
    logger.info("-" * 40)
    logger.info(f"Total Words: {total_words}")
    logger.info(f"Total Duration: {total_duration:.2f}s")
    logger.info(f"Average WPM: {avg_wpm:.2f}")
    logger.info(f"Median WPM: {median_wpm:.2f}")
    logger.info(f"Std Dev: {std_dev:.2f}")
    logger.info(f"Min WPM: {min_wpm:.2f}")
    logger.info(f"Max WPM: {max_wpm:.2f}")
    logger.info("-" * 40)
    logger.info(f"Average Sec/Word: {avg_spw:.3f}")
    logger.info(f"Safe Estimation (Avg - 2*StdDev): {slowest_spw:.3f} s/word")
    logger.info("-" * 40)
    
    # Suggest code update
    print(f"\nRecommended update for step1_analyze.py:")
    print(f"ESTIMATED_SEC_PER_WORD = {slowest_spw:.3f}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=r"v:\Default\Desktop\Self-media\workspace", help="Workspace directory")
    args = parser.parse_args()
    
    calculate_wpm(args.workspace)
