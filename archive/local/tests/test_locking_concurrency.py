import multiprocessing
import time
import msvcrt
import random
import os
from pathlib import Path

def acquire_lock(lock_path, max_retries=100):
    for i in range(max_retries):
        try:
            lock_path.mkdir(exist_ok=False)
            return True
        except FileExistsError:
            time.sleep(random.uniform(0.1, 0.5))
        except Exception as e:
            print(f"Lock error: {e}")
            time.sleep(0.1)
    return False

def release_lock(lock_path):
    try:
        lock_path.rmdir()
    except Exception:
        pass

# Simulation of the robust locking logic
def safe_append(file_path, content, process_id):
    lock_path = Path(file_path).parent / (Path(file_path).name + ".lock")
    
    if acquire_lock(lock_path):
        try:
            with open(file_path, 'a+', encoding='utf-8') as f:
                f.seek(0, 2) # Seek end
                f.write(f"{content}\n")
                f.flush()
                # Keep lock for a bit to simulate work
                time.sleep(0.1) 
            return True
        finally:
            release_lock(lock_path)
    else:
        return False

def worker(file_path, process_id, return_dict):
    if safe_append(file_path, f"Process {process_id} wrote this", process_id):
        return_dict[process_id] = True
        print(f"Process {process_id} SUCCESS")
    else:
        return_dict[process_id] = False
        print(f"Process {process_id} FAILED")

def test_concurrency():
    test_file = Path("test_lock.txt")
    if test_file.exists():
        test_file.unlink()
    
    # Create file first
    with open(test_file, 'w') as f: f.write("")
        
    processes = []
    manager = multiprocessing.Manager()
    return_dict = manager.dict()
    num_processes = 5 # Test with 5 processes
    
    print(f"Starting {num_processes} processes...")
    for i in range(num_processes):
        p = multiprocessing.Process(target=worker, args=(test_file, i, return_dict))
        processes.append(p)
        p.start()
        
    for p in processes:
        p.join()
        
    success_count = sum(1 for v in return_dict.values() if v)
    print(f"Finished. Success count: {success_count}/{num_processes}")
    
    if success_count == num_processes:
        print("TEST PASSED: All processes wrote successfully.")
        
        # Verify content
        with open(test_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            print(f"File line count: {len(lines)}")
            if len(lines) == num_processes:
                print("Content verification PASSED.")
            else:
                print("Content verification FAILED.")
    else:
        print("TEST FAILED: Some processes failed to acquire lock.")

    # Cleanup
    if test_file.exists():
        test_file.unlink()

if __name__ == "__main__":
    test_concurrency()
