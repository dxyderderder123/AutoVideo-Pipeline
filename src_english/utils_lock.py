import time
import random
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def acquire_lock(lock_path: Path, timeout_seconds: float = 60, stale_threshold: float = 300) -> bool:
    """
    Acquire an atomic directory lock.
    
    Args:
        lock_path: Path to the lock directory (e.g., file_path + ".lock")
        timeout_seconds: How long to wait for the lock.
        stale_threshold: Seconds after which a lock is considered stale and can be forcibly removed.
                         Set to 0 or None to disable stale check (not recommended).
    
    Returns:
        True if lock acquired, False otherwise.
    """
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            lock_path.mkdir(exist_ok=False)
            return True
        except FileExistsError:
            # Check for stale lock
            try:
                if stale_threshold and lock_path.exists():
                    mtime = lock_path.stat().st_mtime
                    if time.time() - mtime > stale_threshold:
                        logger.warning(f"Removing stale lock: {lock_path} (Age: {time.time() - mtime:.1f}s)")
                        try:
                            if lock_path.is_dir():
                                try:
                                    lock_path.rmdir()
                                except OSError:
                                    # Directory not empty? Force remove.
                                    import shutil
                                    shutil.rmtree(lock_path, ignore_errors=True)
                            else:
                                # It's a file, remove it
                                lock_path.unlink()
                        except Exception:
                            pass # Maybe someone else removed it
            except Exception as e:
                # e.g. permission error reading stat
                pass
            
            # Wait with jitter to prevent thundering herd
            time.sleep(random.uniform(0.5, 1.5))
        except Exception as e:
            logger.warning(f"Lock error: {e}")
            time.sleep(1)
            
    return False

def release_lock(lock_path: Path):
    """
    Release the atomic directory lock.
    """
    try:
        if lock_path.exists():
            if lock_path.is_dir():
                try:
                    lock_path.rmdir()
                except OSError:
                    import shutil
                    shutil.rmtree(lock_path, ignore_errors=True)
            else:
                lock_path.unlink()
    except Exception as e:
        logger.warning(f"Failed to release lock {lock_path}: {e}")
