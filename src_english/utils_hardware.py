#!/usr/bin/env python3
"""
硬件监控与调度器

监控GPU/CPU/内存使用情况，智能调度任务，防止硬件过载。
提供自适应批处理大小和任务优先级队列。
"""

import os
import time
import threading
import logging
import subprocess
from typing import Optional, Dict, Tuple, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    """任务优先级"""
    CRITICAL = 0  # 关键任务，必须执行
    HIGH = 1      # 高优先级
    NORMAL = 2    # 普通优先级
    LOW = 3       # 低优先级，可延迟


@dataclass
class Task:
    """任务定义"""
    id: str
    priority: TaskPriority
    func: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    gpu_required: bool = False
    gpu_memory_required: float = 0.0  # GB
    cpu_intensive: bool = False
    estimated_duration: float = 0.0   # 秒
    submitted_at: float = field(default_factory=time.time)
    
    def __post_init__(self):
        if not self.id:
            self.id = f"task_{id(self)}"


class GPUManager:
    """
    GPU管理器
    
    监控GPU显存和利用率，协调GPU任务执行
    """
    
    def __init__(self, memory_threshold: float = 0.9):
        """
        Args:
            memory_threshold: 显存使用阈值，超过此值拒绝新任务
        """
        self.memory_threshold = memory_threshold
        self._lock = threading.Lock()
        self._current_tasks: Dict[str, Task] = {}
        
        # 检查CUDA可用性
        self.cuda_available = self._check_cuda()
        
        if self.cuda_available:
            logger.info(f"GPU管理器初始化完成，显存阈值: {memory_threshold*100:.0f}%")
        else:
            logger.warning("CUDA不可用，GPU管理器将以CPU模式运行")
    
    def _check_cuda(self) -> bool:
        """检查CUDA是否可用"""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
    
    def get_memory_info(self) -> Tuple[float, float, float]:
        """
        获取GPU显存信息
        
        Returns:
            (已用GB, 总GB, 使用率)
        """
        if not self.cuda_available:
            return 0.0, 0.0, 0.0
        
        try:
            import torch
            allocated = torch.cuda.memory_allocated() / (1024**3)  # GB
            reserved = torch.cuda.memory_reserved() / (1024**3)    # GB
            
            # 获取总显存
            total = 0
            for i in range(torch.cuda.device_count()):
                total += torch.cuda.get_device_properties(i).total_memory / (1024**3)
            
            usage = allocated / total if total > 0 else 0
            return allocated, total, usage
        except Exception as e:
            logger.warning(f"获取GPU显存信息失败: {e}")
            return 0.0, 0.0, 0.0
    
    def can_accept_task(self, memory_required: float = 0.0) -> bool:
        """
        检查是否可以接受新任务
        
        Args:
            memory_required: 任务需要的显存(GB)
            
        Returns:
            是否可以接受
        """
        if not self.cuda_available:
            return False
        
        allocated, total, usage = self.get_memory_info()
        
        # 检查当前使用率
        if usage > self.memory_threshold:
            return False
        
        # 检查是否有足够剩余显存
        if memory_required > 0:
            available = total * (1 - usage)
            if available < memory_required:
                return False
        
        return True
    
    def wait_for_available(self, memory_required: float = 0.0, timeout: Optional[float] = None) -> bool:
        """
        等待GPU可用
        
        Args:
            memory_required: 需要的显存
            timeout: 超时时间(秒)
            
        Returns:
            是否成功
        """
        start_time = time.time()
        check_interval = 1.0
        
        while True:
            if self.can_accept_task(memory_required):
                return True
            
            if timeout and (time.time() - start_time) > timeout:
                return False
            
            logger.info(f"GPU忙，等待... (当前使用率: {self.get_memory_info()[2]*100:.1f}%)")
            time.sleep(check_interval)
    
    def register_task(self, task: Task):
        """注册任务"""
        with self._lock:
            self._current_tasks[task.id] = task
    
    def unregister_task(self, task_id: str):
        """注销任务"""
        with self._lock:
            self._current_tasks.pop(task_id, None)
    
    def clear_cache(self):
        """清理GPU缓存"""
        if not self.cuda_available:
            return
        
        try:
            import torch
            torch.cuda.empty_cache()
            logger.info("GPU缓存已清理")
        except Exception as e:
            logger.warning(f"清理GPU缓存失败: {e}")
    
    def get_status(self) -> Dict:
        """获取GPU状态"""
        allocated, total, usage = self.get_memory_info()
        
        return {
            "cuda_available": self.cuda_available,
            "allocated_gb": round(allocated, 2),
            "total_gb": round(total, 2),
            "usage_percent": round(usage * 100, 1),
            "threshold_percent": round(self.memory_threshold * 100, 1),
            "active_tasks": len(self._current_tasks),
        }


class CPUMonitor:
    """
    CPU监控器
    
    监控CPU使用率和核心数
    """
    
    def __init__(self, usage_threshold: float = 0.8):
        self.usage_threshold = usage_threshold
        self.cpu_count = os.cpu_count() or 4
        
        logger.info(f"CPU监控器初始化: {self.cpu_count}核心, 阈值{usage_threshold*100:.0f}%")
    
    def get_usage(self) -> float:
        """获取CPU使用率"""
        try:
            # Windows下使用wmic命令
            result = subprocess.run(
                ["wmic", "cpu", "get", "loadpercentage", "/value"],
                capture_output=True,
                text=True,
                timeout=5
            )
            for line in result.stdout.split('\n'):
                if 'LoadPercentage' in line:
                    value = line.split('=')[-1].strip()
                    return float(value) / 100.0
        except Exception:
            pass
        
        return 0.0
    
    def can_accept_task(self, cpu_intensive: bool = False) -> bool:
        """检查是否可以接受新任务"""
        if not cpu_intensive:
            return True
        
        usage = self.get_usage()
        return usage < self.usage_threshold
    
    def get_recommended_workers(self) -> int:
        """获取推荐的worker数量"""
        usage = self.get_usage()
        
        # 根据CPU使用率动态调整
        if usage < 0.3:
            return self.cpu_count
        elif usage < 0.6:
            return max(1, self.cpu_count // 2)
        else:
            return max(1, self.cpu_count // 4)


class HardwareScheduler:
    """
    硬件调度器
    
    统一管理GPU和CPU资源，调度任务执行
    """
    
    def __init__(self):
        import os
        
        # GPU显存阈值 (默认90%)
        memory_threshold = float(os.getenv("SELF_MEDIA_GPU_MEMORY_THRESHOLD", "0.9"))
        self.gpu_manager = GPUManager(memory_threshold=memory_threshold)
        
        # CPU阈值 (默认80%)
        cpu_threshold = float(os.getenv("SELF_MEDIA_CPU_USAGE_THRESHOLD", "0.8"))
        self.cpu_monitor = CPUMonitor(usage_threshold=cpu_threshold)
        
        # 任务队列 (按优先级排序)
        self._task_queue: deque[Task] = deque()
        self._queue_lock = threading.Lock()
        
        # 统计
        self._stats = {
            "submitted": 0,
            "completed": 0,
            "failed": 0,
            "gpu_tasks": 0,
            "cpu_tasks": 0,
        }
        self._stats_lock = threading.Lock()
        
        logger.info("硬件调度器初始化完成")
    
    def submit_task(self, task: Task) -> bool:
        """
        提交任务到队列
        
        Args:
            task: 任务定义
            
        Returns:
            是否成功提交
        """
        with self._queue_lock:
            # 按优先级插入队列
            inserted = False
            for i, existing_task in enumerate(self._task_queue):
                if task.priority.value < existing_task.priority.value:
                    self._task_queue.insert(i, task)
                    inserted = True
                    break
            
            if not inserted:
                self._task_queue.append(task)
        
        with self._stats_lock:
            self._stats["submitted"] += 1
        
        logger.debug(f"任务提交: {task.id} (优先级: {task.priority.name})")
        return True
    
    def get_next_task(self) -> Optional[Task]:
        """获取下一个可执行的任务"""
        with self._queue_lock:
            for i, task in enumerate(self._task_queue):
                # 检查资源需求
                if task.gpu_required:
                    if not self.gpu_manager.can_accept_task(task.gpu_memory_required):
                        continue
                elif task.cpu_intensive:
                    if not self.cpu_monitor.can_accept_task(True):
                        continue
                
                # 找到可执行的任务
                self._task_queue.remove(task)
                return task
            
            return None
    
    def execute_task(self, task: Task) -> Any:
        """
        执行任务
        
        Args:
            task: 任务定义
            
        Returns:
            任务返回值
        """
        # 注册GPU任务
        if task.gpu_required:
            self.gpu_manager.register_task(task)
        
        try:
            logger.info(f"执行任务: {task.id} (GPU: {task.gpu_required})")
            
            start_time = time.time()
            result = task.func(*task.args, **task.kwargs)
            duration = time.time() - start_time
            
            with self._stats_lock:
                self._stats["completed"] += 1
                if task.gpu_required:
                    self._stats["gpu_tasks"] += 1
                else:
                    self._stats["cpu_tasks"] += 1
            
            logger.info(f"任务完成: {task.id} (耗时: {duration:.1f}s)")
            return result
            
        except Exception as e:
            with self._stats_lock:
                self._stats["failed"] += 1
            
            logger.error(f"任务失败: {task.id}: {e}")
            raise
        finally:
            if task.gpu_required:
                self.gpu_manager.unregister_task(task.id)
                # 清理GPU缓存
                self.gpu_manager.clear_cache()
    
    def wait_and_execute(self, task: Task, timeout: Optional[float] = None) -> Any:
        """
        等待资源可用后执行任务
        
        Args:
            task: 任务定义
            timeout: 超时时间
            
        Returns:
            任务返回值
        """
        start_time = time.time()
        
        # 等待GPU资源
        if task.gpu_required:
            if not self.gpu_manager.wait_for_available(
                task.gpu_memory_required, timeout
            ):
                raise RuntimeError(f"等待GPU资源超时: {task.id}")
        
        # 等待CPU资源
        if task.cpu_intensive:
            while not self.cpu_monitor.can_accept_task(True):
                if timeout and (time.time() - start_time) > timeout:
                    raise RuntimeError(f"等待CPU资源超时: {task.id}")
                time.sleep(0.5)
        
        return self.execute_task(task)
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._stats_lock:
            return self._stats.copy()
    
    def get_queue_length(self) -> int:
        """获取队列长度"""
        with self._queue_lock:
            return len(self._task_queue)
    
    def get_status(self) -> Dict:
        """获取整体状态"""
        return {
            "gpu": self.gpu_manager.get_status(),
            "queue_length": self.get_queue_length(),
            "stats": self.get_stats(),
        }


# 全局硬件调度器实例
hardware_scheduler = HardwareScheduler()


def schedule_gpu_task(
    func: Callable,
    *args,
    priority: TaskPriority = TaskPriority.NORMAL,
    memory_required: float = 0.0,
    timeout: Optional[float] = None,
    **kwargs
) -> Any:
    """
    调度GPU任务
    
    便捷函数，创建任务并等待执行
    """
    task = Task(
        id=f"gpu_task_{int(time.time()*1000)}",
        priority=priority,
        func=func,
        args=args,
        kwargs=kwargs,
        gpu_required=True,
        gpu_memory_required=memory_required,
    )
    
    return hardware_scheduler.wait_and_execute(task, timeout)


def schedule_cpu_task(
    func: Callable,
    *args,
    priority: TaskPriority = TaskPriority.NORMAL,
    cpu_intensive: bool = False,
    timeout: Optional[float] = None,
    **kwargs
) -> Any:
    """
    调度CPU任务
    
    便捷函数，创建任务并等待执行
    """
    task = Task(
        id=f"cpu_task_{int(time.time()*1000)}",
        priority=priority,
        func=func,
        args=args,
        kwargs=kwargs,
        cpu_intensive=cpu_intensive,
    )
    
    return hardware_scheduler.wait_and_execute(task, timeout)


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    # 测试GPU状态
    print("GPU状态:")
    print(hardware_scheduler.gpu_manager.get_status())
    
    # 测试CPU状态
    print("\nCPU状态:")
    print(f"  核心数: {hardware_scheduler.cpu_monitor.cpu_count}")
    print(f"  使用率: {hardware_scheduler.cpu_monitor.get_usage()*100:.1f}%")
    print(f"  推荐workers: {hardware_scheduler.cpu_monitor.get_recommended_workers()}")
    
    # 测试任务调度
    def mock_gpu_task():
        print("  执行GPU任务...")
        time.sleep(1)
        return "GPU任务完成"
    
    def mock_cpu_task():
        print("  执行CPU任务...")
        time.sleep(0.5)
        return "CPU任务完成"
    
    print("\n测试任务调度:")
    
    # 提交GPU任务
    if hardware_scheduler.gpu_manager.cuda_available:
        result = schedule_gpu_task(mock_gpu_task, memory_required=1.0)
        print(f"  结果: {result}")
    else:
        print("  CUDA不可用，跳过GPU测试")
    
    # 提交CPU任务
    result = schedule_cpu_task(mock_cpu_task, cpu_intensive=True)
    print(f"  结果: {result}")
    
    # 打印统计
    print("\n调度器统计:")
    print(hardware_scheduler.get_stats())
