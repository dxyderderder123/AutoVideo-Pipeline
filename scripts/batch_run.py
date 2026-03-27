import os
import sys
import subprocess
import logging
from pathlib import Path
import datetime
import time

# --- Custom Logging Setup to support File + Console Streaming ---
def setup_logging_file(project_root):
    """
    Sets up a log file in the logs/ directory.
    Returns: file handle (or None if failed), log_file_path
    """
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file_path = logs_dir / f"batch_run_{timestamp}.log"
    
    try:
        f = open(log_file_path, "a", encoding="utf-8")
        return f, log_file_path
    except Exception as e:
        print(f"Warning: Could not create log file: {e}")
        return None, None

def log_msg(file_handle, message, level="INFO"):
    """
    Logs a message to console and file with a timestamp header.
    Used for batch_run.py's own messages.
    """
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
    formatted_msg = f"{timestamp} - {level} - {message}"
    
    # Console
    print(formatted_msg)
    
    # File
    if file_handle:
        try:
            file_handle.write(formatted_msg + "\n")
            file_handle.flush()
        except Exception:
            pass

def run_command_logged(cmd, file_handle):
    """
    Runs a subprocess command, capturing stdout/stderr and streaming them 
    to both console and the log file.
    Does NOT add extra timestamps to subprocess output (preserves original format).
    """
    try:
        # Start process with stdout/stderr piped
        # bufsize=1 means line buffered
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # Merge stderr into stdout
            text=True,
            encoding='utf-8',
            errors='replace', # Replace decoding errors instead of crashing
            bufsize=1
        )
        
        # Read line by line
        for line in process.stdout:
            # Print to console (sys.stdout)
            sys.stdout.write(line)
            # Write to file
            if file_handle:
                file_handle.write(line)
                
        # Wait for process to finish
        process.wait()
        
        # Flush file
        if file_handle:
            file_handle.flush()
            
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)
            
    except Exception as e:
        # Re-raise to be caught by caller
        raise e

# ----------------------------------------------------------------

def get_venv_python(log_file_handle):
    """Get the path to the virtual environment python executable"""
    # Try to find the venv python based on the current file location
    # Assuming batch_run.py is in the project root
    project_root = Path(__file__).parent.absolute()
    
    # Try common venv locations
    venv_paths = [
        project_root / "venv" / "Scripts" / "python.exe", # Windows
        project_root / "venv" / "bin" / "python",         # Linux/Mac
        project_root / ".venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "bin" / "python"
    ]
    
    for path in venv_paths:
        if path.exists():
            return str(path)
            
    # Fallback to sys.executable if it looks like a venv
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        return sys.executable
        
    log_msg(log_file_handle, "Could not locate venv python. Using system python, which might fail if dependencies are missing.", "WARNING")
    return sys.executable

def main():
    # scripts目录的父目录是项目根目录
    project_root = Path(__file__).parent.parent.absolute()
    
    # 1. Setup Logging File
    log_file, log_path = setup_logging_file(project_root)
    if log_path:
        print(f"Logging execution to: {log_path}")
    
    input_dir = project_root / "workspace" / "input"
    
    # Generate date-based output directory (YYMMDD)
    # e.g. workspace/output/260203
    today_str = datetime.datetime.now().strftime("%y%m%d")
    output_dir = project_root / "workspace" / "output" / today_str
    
    # Ensure directories exist
    if not input_dir.exists():
        log_msg(log_file, f"Input directory not found: {input_dir}", "ERROR")
        if log_file: log_file.close()
        return
        
    output_dir.mkdir(parents=True, exist_ok=True)
    log_msg(log_file, f"Output directory: {output_dir}")
    
    # Find all .md files
    md_files = list(input_dir.glob("*.md"))
    
    if not md_files:
        log_msg(log_file, f"No markdown files found in {input_dir}", "WARNING")
        if log_file: log_file.close()
        return
        
    log_msg(log_file, f"Found {len(md_files)} markdown files to process: {[f.name for f in md_files]}")
    
    venv_python = get_venv_python(log_file)
    log_msg(log_file, f"Using Python interpreter: {venv_python}")
    
    success_count = 0
    fail_count = 0
    
    import concurrent.futures
    import threading
    
    # Lock for log file writing to prevent interleaving
    log_lock = threading.Lock()
    
    def process_single_file(md_file):
        input_filename = md_file.name
        output_filename = md_file.stem + ".mp4"
        final_output_path = output_dir / output_filename
        
        # Create separate log file for this task to avoid interleaving
        logs_dir = project_root / "logs"
        task_log_filename = f"run_{datetime.datetime.now().strftime('%H%M%S')}_{md_file.stem}.log"
        task_log_path = logs_dir / task_log_filename
        
        with log_lock:
            log_msg(log_file, f"START: {input_filename}")
            log_msg(log_file, f"   > Task Log: {task_log_filename}")
        
        # Construct command
        # 优化: 支持通过环境变量控制批量任务参数
        skip_upload = os.environ.get("SELF_MEDIA_BATCH_SKIP_UPLOAD", "0") == "1"
        preview_mode = os.environ.get("SELF_MEDIA_BATCH_PREVIEW", "0") == "1"
        
        cmd = [
            venv_python,
            str(project_root / "main.py"),
            "--input", input_filename,
        ]
        
        if skip_upload:
            cmd.append("--skip_upload")
        if preview_mode:
            cmd.append("--preview")
        
        cmd.extend(["--final_output", str(final_output_path)])
        
        try:
            # Run with private log handle
            with open(task_log_path, "w", encoding="utf-8") as task_log:
                task_log.write(f"Processing {input_filename} at {datetime.datetime.now()}\n")
                task_log.write(f"Command: {' '.join(cmd)}\n")
                task_log.write("-" * 60 + "\n")
                task_log.flush()
                
                # Execute subprocess and stream to private log file ONLY
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, # Merge stderr into stdout
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=1
                )
                
                # Stream output to file and console (with prefix)
                for line in process.stdout:
                    task_log.write(line)
                    # Print to console with prefix to distinguish parallel tasks
                    # Using sys.stdout.write to avoid double newlines
                    try:
                        sys.stdout.write(f"[{md_file.stem}] {line}")
                        sys.stdout.flush()
                    except Exception:
                        pass
                
                process.wait()
                try:
                    if process.stdout:
                        process.stdout.close()
                except Exception:
                    pass
                
                if process.returncode != 0:
                    raise subprocess.CalledProcessError(process.returncode, cmd)
            
            with log_lock:
                log_msg(log_file, f"SUCCESS: {input_filename}")
            return True
            
        except subprocess.CalledProcessError as e:
            with log_lock:
                log_msg(log_file, f"FAILURE: {input_filename} (Exit: {e.returncode})", "ERROR")
                log_msg(log_file, f"   > Check log: {task_log_filename}", "ERROR")
            return False
        except Exception as e:
            with log_lock:
                log_msg(log_file, f"ERROR: {input_filename}: {e}", "ERROR")
            return False

    # Concurrency Configuration
    # Default to conservative settings to avoid saturating CPU/RAM/GPU on typical desktops.
    # You can override via environment variable:
    #   SELF_MEDIA_MAX_BATCH_WORKERS=1/2/3...
    #
    # 智能并发建议:
    # - GPU 8GB以下: 建议 1 (避免OOM)
    # - GPU 8-12GB: 建议 1-2
    # - GPU 16GB+: 建议 2-3
    # - 无GPU (CPU模式): 建议 1-2
    try:
        default_workers = 1
        # 尝试检测GPU显存来自动设置
        try:
            import torch
            if torch.cuda.is_available():
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)  # GB
                if gpu_memory >= 16:
                    default_workers = 2
                elif gpu_memory >= 8:
                    default_workers = 1
                else:
                    default_workers = 1
                log_msg(log_file, f"Detected GPU with {gpu_memory:.1f}GB VRAM. Default batch workers: {default_workers}")
        except Exception:
            pass
        
        MAX_BATCH_WORKERS = max(1, int(os.environ.get("SELF_MEDIA_MAX_BATCH_WORKERS", str(default_workers))))
    except Exception:
        MAX_BATCH_WORKERS = 1
    
    log_msg(log_file, f"Batch processing with {MAX_BATCH_WORKERS} parallel workers")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_BATCH_WORKERS) as executor:
        futures = {executor.submit(process_single_file, md_file): md_file for md_file in md_files}
        
        for future in concurrent.futures.as_completed(futures):
            md_file = futures[future]
            try:
                result = future.result()
                if result:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                with log_lock:
                    log_msg(log_file, f"Exception in batch thread for {md_file}: {e}", "ERROR")
                fail_count += 1

    log_msg(log_file, f"================================================================")
    log_msg(log_file, f"Batch Processing Complete. Success: {success_count}, Failed: {fail_count}")
    log_msg(log_file, f"================================================================")
    
    if log_file:
        log_file.close()

if __name__ == "__main__":
    main()
