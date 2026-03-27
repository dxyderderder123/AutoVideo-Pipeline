#!/usr/bin/env python3
"""
优化功能测试脚本
"""
import sys
sys.path.insert(0, 'src_english')

def test_basic_imports():
    """测试基础模块导入"""
    print("测试基础模块导入...")
    from utils_rate_limiter import rate_limiter
    from utils_hardware import hardware_scheduler
    from utils_downloader import get_downloader
    from workflow import PipelineStats
    print("✓ 所有基础模块导入成功")

def test_pipeline_stats():
    """测试统计功能"""
    print("\n测试统计功能...")
    from workflow import PipelineStats
    import time
    
    stats = PipelineStats()
    stats.record_step_start('test')
    time.sleep(0.1)
    stats.record_step_end('test')
    
    duration = stats.step_times.get('test', 0)
    print(f"✓ 统计功能正常: test步骤耗时 {duration:.3f}s")

def test_gpu_status():
    """测试GPU状态"""
    print("\n测试GPU状态...")
    from utils_hardware import hardware_scheduler
    
    gpu_status = hardware_scheduler.gpu_manager.get_status()
    print(f"✓ GPU状态: {gpu_status}")

def test_rate_limiter():
    """测试限流管理器"""
    print("\n测试限流管理器...")
    from utils_rate_limiter import rate_limiter
    
    # 获取统计
    stats = rate_limiter.get_all_stats()
    print(f"✓ 限流管理器统计: {list(stats.keys())}")

def test_downloader():
    """测试下载管理器"""
    print("\n测试下载管理器...")
    from utils_downloader import get_downloader
    
    downloader = get_downloader()
    print(f"✓ 下载管理器初始化成功")

def test_step_imports():
    """测试各步骤模块导入"""
    print("\n测试各步骤模块导入...")
    
    from step1_analyze import analyze_text
    print("✓ step1_analyze")
    
    from step3_video import search_pixabay
    print("✓ step3_video")
    
    from step6_translate import translate_batch
    print("✓ step6_translate")
    
    from step8_cover import generate_cover_prompt
    print("✓ step8_cover")

def main():
    print("=" * 60)
    print("优化功能测试")
    print("=" * 60)
    
    try:
        test_basic_imports()
        test_pipeline_stats()
        test_gpu_status()
        test_rate_limiter()
        test_downloader()
        test_step_imports()
        
        print("\n" + "=" * 60)
        print("所有测试通过!")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
