
import sys
import os

print(f"Python Executable: {sys.executable}")
print(f"CWD: {os.getcwd()}")

try:
    import whisperx
    print("SUCCESS: whisperx imported")
    print(f"whisperx file: {whisperx.__file__}")
except ImportError as e:
    print(f"FAILURE: {e}")
except Exception as e:
    print(f"ERROR: {e}")

try:
    import torch
    print(f"SUCCESS: torch imported (Version: {torch.__version__})")
except ImportError:
    print("FAILURE: torch not found")
