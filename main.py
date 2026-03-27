#!/usr/bin/env python3
"""
Self-Media Video Generation Pipeline

自动化英文学习视频生成系统入口

Usage:
    python main.py --input test.md
    python main.py --input test.md --preview  # 预览模式(480p快速渲染)
    python main.py --input test.md --skip_upload  # 跳过上传
    python main.py --input test.md --final_output output/video.mp4
"""

import sys
import os
from pathlib import Path

# Add src_english to sys.path so we can import modules from it
src_path = Path(__file__).resolve().parent / "src_english"
sys.path.insert(0, str(src_path))

# 设置环境变量默认值
os.environ.setdefault("SELF_MEDIA_LOG_LEVEL", "INFO")
os.environ.setdefault("SELF_MEDIA_PARALLEL_WORKERS", "3")

if __name__ == "__main__":
    try:
        # Import the main workflow module
        from workflow import main
        main()
    except ImportError as e:
        print(f"Error starting application: {e}")
        print(f"sys.path: {sys.path}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n用户中断执行")
        sys.exit(130)
    except Exception as e:
        print(f"执行错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
