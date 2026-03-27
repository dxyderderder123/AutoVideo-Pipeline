import sys
import os
import time
import argparse
import subprocess
import logging
import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field

# Setup logging
_log_level = os.environ.get("SELF_MEDIA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _log_level, logging.INFO), format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from config import INPUT_DIR, TEMP_BASE_DIR, CLEANUP_TEMP_DIR, FINISH_RECORD_FILE

# Use shared locking module
try:
    from utils_lock import acquire_lock, release_lock
except ImportError:
    import sys
    sys.path.append(str(Path(__file__).parent))
    from utils_lock import acquire_lock, release_lock

# 尝试导入性能监控工具
try:
    from utils_rate_limiter import rate_limiter
    from utils_hardware import hardware_scheduler
    _utils_available = True
except ImportError:
    _utils_available = False
    logger.warning("性能监控工具不可用")


@dataclass
class PipelineStats:
    """流水线统计信息"""
    start_time: float = field(default_factory=time.time)
    step_times: Dict[str, float] = field(default_factory=dict)
    errors: list = field(default_factory=list)
    
    def record_step_start(self, step_name: str):
        """记录步骤开始"""
        self.step_times[f"{step_name}_start"] = time.time()
        logger.info(f"[统计] 步骤 {step_name} 开始")
    
    def record_step_end(self, step_name: str):
        """记录步骤结束"""
        start_key = f"{step_name}_start"
        if start_key in self.step_times:
            duration = time.time() - self.step_times[start_key]
            self.step_times[step_name] = duration
            logger.info(f"[统计] 步骤 {step_name} 完成，耗时: {duration:.1f}s")
    
    def record_error(self, step_name: str, error: str):
        """记录错误"""
        self.errors.append({"step": step_name, "error": error, "time": time.time()})
    
    def print_summary(self):
        """打印统计摘要"""
        total_time = time.time() - self.start_time
        logger.info("=" * 60)
        logger.info("流水线执行统计")
        logger.info("=" * 60)
        logger.info(f"总耗时: {total_time:.1f}s ({total_time/60:.1f}分钟)")
        logger.info("\n各步骤耗时:")
        for step_name in ["step1", "step2", "step3", "step5", "step6", "step7", "step8", "step9"]:
            if step_name in self.step_times:
                duration = self.step_times[step_name]
                percentage = (duration / total_time * 100) if total_time > 0 else 0
                logger.info(f"  {step_name}: {duration:.1f}s ({percentage:.1f}%)")
        
        if self.errors:
            logger.info(f"\n错误数: {len(self.errors)}")
            for err in self.errors:
                logger.error(f"  {err['step']}: {err['error']}")
        
        # 打印API限流统计
        if _utils_available:
            try:
                rate_limiter.print_stats()
            except:
                pass
        
        logger.info("=" * 60)

def record_finished_video(input_path: Path):
    """
    Appends the processed video title to finish.md with a date header.
    Format:
    # YYMMDD
    Title
    """
    try:
        # Get Title (First line of input file)
        title = input_path.stem # Default to filename
        if input_path.exists():
            with open(input_path, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
                if first_line:
                    title = first_line.replace("#", "").strip() # Remove markdown header chars
        
        today_str = datetime.now().strftime("%y%m%d")
        header = f"# {today_str}"
        
        lock_path = FINISH_RECORD_FILE.parent / (FINISH_RECORD_FILE.name + ".lock")
        if not FINISH_RECORD_FILE.parent.exists():
            FINISH_RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)

        if acquire_lock(lock_path, timeout_seconds=100):
            try:
                lines = []
                if FINISH_RECORD_FILE.exists():
                    with open(FINISH_RECORD_FILE, 'r', encoding='utf-8') as f:
                        lines = f.read().splitlines()
                
                header_exists = False
                if lines:
                    for line in reversed(lines):
                        if line.startswith("# "):
                            if line.strip() == header:
                                header_exists = True
                            break
                
                with open(FINISH_RECORD_FILE, 'a', encoding='utf-8') as f:
                    # Append if needed
                    if not header_exists:
                        if lines and lines[-1].strip(): 
                            f.write("\n") 
                        f.write(f"{header}\n")
                    
                    f.write(f"{title}\n")
                    
                logger.info(f"Recorded video to history: {title}")
            except Exception as e:
                 logger.warning(f"Error accessing finish record: {e}")
            finally:
                release_lock(lock_path)
        else:
            logger.warning(f"Failed to record video to history: Could not acquire lock.")

    except Exception as e:
        logger.error(f"Failed to record finished video: {e}")

def check_environment():
    """Verify required tools and environment variables"""
    # Check FFmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("FFmpeg not found. Please install FFmpeg and add to PATH.")
        return False
        
    # Check Python environment (basic)
    try:
        import requests
        import numpy
        import torch
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        return False
        
    return True

def merge_analysis_jsons(tts_json_path, video_json_path, output_json_path):
    """Merge TTS and Video analysis results"""
    if not tts_json_path.exists() or not video_json_path.exists():
        logger.error(f"Missing analysis files for merge: {tts_json_path} or {video_json_path}")
        return False
        
    try:
        with open(tts_json_path, 'r', encoding='utf-8') as f:
            tts_data = json.load(f)
        with open(video_json_path, 'r', encoding='utf-8') as f:
            video_data = json.load(f)
            
        # Create a map of video segments by ID
        video_map = {seg['id']: seg for seg in video_data.get('segments', [])}
        
        # Merge video info into TTS data (which has accurate audio duration)
        for seg in tts_data.get('segments', []):
            seg_id = seg.get('id')
            if seg_id in video_map:
                v_seg = video_map[seg_id]
                if 'video_file' in v_seg:
                    seg['video_file'] = v_seg['video_file']
                if 'video_files' in v_seg:
                    seg['video_files'] = v_seg['video_files']
                if 'video_source' in v_seg:
                    seg['video_source'] = v_seg['video_source']
                    
        # Save merged
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(tts_data, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Merged analysis saved to {output_json_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to merge analysis JSONs: {e}")
        return False

def run_step(script_name, args):
    script_path = Path(__file__).parent / script_name
    
    # Force use of venv python
    project_root = Path(__file__).parent.parent
    venv_python = project_root / "venv" / "Scripts" / "python.exe"
    
    if venv_python.exists():
        python_exe = str(venv_python)
    else:
        logger.warning(f"Venv python not found at {venv_python}, falling back to sys.executable")
        python_exe = sys.executable

    cmd = [python_exe, str(script_path)] + args
    
    logger.info(f"Running {script_name}...")
    try:
        subprocess.run(cmd, check=True)
        logger.info(f"{script_name} completed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"{script_name} failed with exit code {e.returncode}")
        return False

def run_step_with_stats(script_name: str, args: list, stats: PipelineStats) -> bool:
    """
    运行步骤并记录统计信息
    
    Args:
        script_name: 脚本名称
        args: 参数列表
        stats: 统计对象
        
    Returns:
        是否成功
    """
    step_name = script_name.replace(".py", "")
    stats.record_step_start(step_name)
    
    try:
        result = run_step(script_name, args)
        if result:
            stats.record_step_end(step_name)
            return True
        else:
            stats.record_error(step_name, "执行失败")
            return False
    except Exception as e:
        stats.record_error(step_name, str(e))
        raise


def main():
    parser = argparse.ArgumentParser(description="Automated Video Generation Pipeline")
    parser.add_argument("--input", type=str, default="test.md", help="Input markdown filename in workspace/input")
    parser.add_argument("--final_output", type=str, default=None, help="Optional path to copy the final video to")
    parser.add_argument("--skip_upload", action="store_true", help="Skip upload step")
    parser.add_argument("--preview", action="store_true", help="Enable preview mode (480p fast render)")
    args = parser.parse_args()
    
    # 初始化统计
    stats = PipelineStats()
    
    input_filename = args.input
    input_path = INPUT_DIR / input_filename
    
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return

    # Create timestamped temp directory
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    project_name = input_path.stem
    temp_dir = TEMP_BASE_DIR / f"{project_name}_{timestamp}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Initialized project: {project_name}")
    logger.info(f"Temp directory: {temp_dir}")
    
    # 设置预览模式环境变量
    if args.preview:
        os.environ["SELF_MEDIA_PREVIEW_MODE"] = "1"
        logger.info("启用预览模式 (480p快速渲染)")
    
    # Define paths
    analysis_json = temp_dir / "analysis.json"
    tts_dir = temp_dir / "tts"
    video_dir = temp_dir / "video"
    audio_dir = temp_dir / "audio"
    video_720p_dir = temp_dir / "video_720p"
    output_dir = temp_dir / "output"
    
    if not check_environment():
        logger.error("Environment check failed. Please check logs.")
        return

    # Step 1: Analyze
    if not run_step_with_stats("step1_analyze.py", [str(input_path), str(analysis_json)], stats):
        stats.print_summary()
        sys.exit(1)
        
    import concurrent.futures
    
    # Parallel Execution Strategy
    # Group A: TTS Generation (step2)
    # Group B: Video Acquisition (step3)
    # Group C: Cover Generation (step8) - Completely independent
    
    logger.info("Starting parallel execution of TTS, Video, and Cover generation...")
    
    analysis_tts_json = temp_dir / "analysis_tts.json"
    analysis_video_json = temp_dir / "analysis_video_only.json"
    
    try:
        parallel_workers = max(1, int(os.environ.get("SELF_MEDIA_PARALLEL_WORKERS", "3")))
    except Exception:
        parallel_workers = 3

    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        # Submit tasks
        # Step 8: Cover (Independent)
        future_cover = executor.submit(
            run_step_with_stats, 
            "step8_cover.py", 
            ["--input_file", str(input_path), "--output_dir", str(output_dir)],
            stats
        )
        
        # Step 2: TTS (Depends on analysis.json)
        future_tts = executor.submit(
            run_step_with_stats, 
            "step2_tts.py", 
            ["--input_json", str(analysis_json), "--output_dir", str(tts_dir)],
            stats
        )
        
        # Step 3: Video (Parallel with TTS)
        future_video = executor.submit(
            run_step_with_stats, 
            "step3_video.py", 
            ["--input_json", str(analysis_json), "--output_dir", str(video_dir), "--output_json", str(analysis_video_json)],
            stats
        )
        
        # Wait for TTS and Video
        if not future_tts.result():
            logger.error("TTS generation failed. Aborting.")
            stats.print_summary()
            sys.exit(1)
            
        if not future_video.result():
            logger.error("Video acquisition failed. Aborting.")
            stats.print_summary()
            sys.exit(1)

    # Merge JSONs
    analysis_merged_json = temp_dir / "analysis_merged.json"
    if not merge_analysis_jsons(analysis_tts_json, analysis_video_json, analysis_merged_json):
        logger.error("Failed to merge analysis JSONs.")
        stats.print_summary()
        sys.exit(1)
    
    final_json_input = analysis_merged_json

    # Step 5: Subtitle
    if not run_step_with_stats("step5_subtitle.py", ["--dir", str(temp_dir)], stats):
        stats.print_summary()
        sys.exit(1)

    # Step 6: Translate
    if not run_step_with_stats("step6_translate.py", ["--srt_path", str(output_dir / "subtitles.srt"), "--output_dir", str(output_dir)], stats):
        stats.print_summary()
        sys.exit(1)

    # Step 7: Merge
    logger.info("Step 7: Final Merge (Video + TTS + Subtitles + End Note)...")
    input_stem = Path(args.input).stem
    
    if not run_step_with_stats("step7_merge.py", [
        "--input_json", str(final_json_input), 
        "--output_dir", str(output_dir),
        "--filename", input_stem
    ], stats):
        stats.print_summary()
        sys.exit(1)

    # Ensure Cover Generation is complete
    if not future_cover.result():
        logger.warning("Cover generation failed. Proceeding without cover.")

    # Step 9: Upload to Bilibili
    final_video_path = output_dir / "final_video.mp4"
    cover_image_path = output_dir / f"{input_stem}_horizontal.jpg"
    
    if not args.skip_upload:
        if not run_step_with_stats("step9_upload.py", [
            "--video_path", str(final_video_path),
            "--cover_path", str(cover_image_path),
            "--title_file", str(input_path),
            "--desc", f"Generated by VibeVoice & FastVideo Pipeline. Source: {input_stem}"
        ], stats):
            logger.warning("Upload step failed or was skipped.")
    else:
        logger.info("跳过上传步骤 (--skip_upload)")

    logger.info("Pipeline completed successfully!")
    logger.info(f"Final output: {output_dir}")
    
    # Handle final output copy if requested
    if args.final_output:
        target_path = Path(args.final_output)
        target_dir = target_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Copy Video
        final_video_path = output_dir / "final_video.mp4"
        if final_video_path.exists():
            try:
                shutil.copy2(final_video_path, target_path)
                logger.info(f"Copied final video to: {target_path}")
            except Exception as e:
                logger.error(f"Failed to copy final video: {e}")
        
        # 2. Copy Covers
        # Find all generated covers (horizontal and vertical)
        for cover_file in output_dir.glob("*_horizontal.jpg"):
            try:
                # Copy with same name
                shutil.copy2(cover_file, target_dir / cover_file.name)
                logger.info(f"Copied horizontal cover to: {target_dir / cover_file.name}")
            except Exception as e:
                logger.error(f"Failed to copy cover {cover_file}: {e}")
                
        for cover_file in output_dir.glob("*_vertical.jpg"):
            try:
                shutil.copy2(cover_file, target_dir / cover_file.name)
                logger.info(f"Copied vertical cover to: {target_dir / cover_file.name}")
            except Exception as e:
                logger.error(f"Failed to copy cover {cover_file}: {e}")

    # Archive/History Logic (Updated per user request)
    # Copy the processed input file directly to the output timestamp directory
    # e.g., workspace/output/260212/filename.md
    try:
        shutil.copy2(input_path, output_dir / input_path.name)
        logger.info(f"Copied input file to output history: {output_dir / input_path.name}")
    except Exception as e:
        logger.warning(f"Failed to copy input file to output history: {e}")

    if args.final_output:
        # Copy final video to requested location
        final_output_path = Path(args.final_output)
        final_output_path.parent.mkdir(parents=True, exist_ok=True)
        output_video = output_dir / "final_video.mp4"
        
        if output_video.exists():
            try:
                shutil.copy2(output_video, final_output_path)
                logger.info(f"Final video copied to: {final_output_path}")
                
                # Record to finish.md
                record_finished_video(input_path)
                
                # Cleanup Temp Directory on Success (Only if copy succeeded and enabled in config)
                if CLEANUP_TEMP_DIR:
                    try:
                        logger.info(f"Cleaning up temp directory: {temp_dir}")
                        shutil.rmtree(temp_dir)
                    except Exception as e:
                        logger.warning(f"Failed to cleanup temp dir {temp_dir}: {e}")
                else:
                    logger.info(f"Cleanup skipped (CLEANUP_TEMP_DIR=False). Temp dir: {temp_dir}")
            except Exception as e:
                logger.error(f"Failed to copy final video to {final_output_path}: {e}")
        else:
            logger.error(f"Output video not found at {output_video}")
            
    else:
        logger.info(f"Final video is in: {output_dir / 'final_video.mp4'}")
        logger.info(f"Temp directory preserved: {temp_dir}")
    
    # 打印执行统计
    stats.print_summary()
    
    # 保存详细统计到文件
    try:
        stats_file = output_dir / "pipeline_stats.json"
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump({
                "step_times": stats.step_times,
                "errors": stats.errors,
                "total_time": time.time() - stats.start_time
            }, f, indent=2, ensure_ascii=False)
        logger.info(f"统计信息已保存: {stats_file}")
    except Exception as e:
        logger.warning(f"保存统计信息失败: {e}")

if __name__ == "__main__":
    main()
