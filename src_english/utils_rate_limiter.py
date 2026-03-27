#!/usr/bin/env python3
"""
统一API限流管理器

使用令牌桶算法统一管理所有外部API的调用速率，防止触发服务商限额墙。
支持DeepSeek, Pixabay, Pexels, SiliconCloud等服务的限流控制。
"""

import time
import threading
import random
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """限流配置"""
    rpm: int = 60  # 每分钟请求数
    concurrent: int = 3  # 最大并发数
    burst: int = 5  # 突发容量
    retry_attempts: int = 3  # 失败重试次数
    retry_delay_base: float = 1.0  # 基础重试延迟(秒)


class TokenBucket:
    """
    令牌桶算法实现
    
    以恒定速率生成令牌，请求需要消耗令牌才能执行。
    当令牌不足时，请求需要等待。
    """
    
    def __init__(self, rate: float, capacity: int):
        """
        Args:
            rate: 令牌生成速率 (令牌/秒)
            capacity: 桶容量 (最大突发请求数)
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity  # 初始满桶
        self.last_update = time.time()
        self._lock = threading.Lock()
    
    def _add_tokens(self):
        """根据时间流逝添加令牌"""
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now
    
    def acquire(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """
        尝试获取令牌
        
        Args:
            tokens: 需要的令牌数
            timeout: 最大等待时间(秒)，None表示无限等待
            
        Returns:
            是否成功获取令牌
        """
        start_time = time.time()
        
        while True:
            with self._lock:
                self._add_tokens()
                
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
                
                # 计算需要等待的时间
                tokens_needed = tokens - self.tokens
                wait_time = tokens_needed / self.rate
                
                # 检查是否超时
                if timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed + wait_time > timeout:
                        return False
            
            # 等待后重试
            time.sleep(min(wait_time, 0.1))  # 最多等待100ms后检查
    
    def try_acquire(self, tokens: int = 1) -> bool:
        """非阻塞尝试获取令牌"""
        with self._lock:
            self._add_tokens()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


class ServiceRateLimiter:
    """
    单个服务的限流器
    
    结合令牌桶和并发控制
    """
    
    def __init__(self, name: str, config: RateLimitConfig):
        self.name = name
        self.config = config
        
        # 令牌桶 (rpm转换为每秒令牌数)
        rate_per_second = config.rpm / 60.0
        self.bucket = TokenBucket(rate_per_second, config.burst)
        
        # 并发控制
        self.semaphore = threading.Semaphore(config.concurrent)
        
        # 统计
        self.stats = {
            "total_requests": 0,
            "throttled_requests": 0,
            "failed_requests": 0,
            "retry_attempts": 0,
        }
        self._stats_lock = threading.Lock()
    
    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        获取执行许可
        
        先获取令牌桶许可，再获取并发许可
        """
        # 1. 获取令牌
        if not self.bucket.acquire(1, timeout):
            with self._stats_lock:
                self.stats["throttled_requests"] += 1
            logger.warning(f"[{self.name}] 限流: 无法获取令牌")
            return False
        
        # 2. 获取并发许可
        if not self.semaphore.acquire(timeout=timeout):
            return False
        
        with self._stats_lock:
            self.stats["total_requests"] += 1
        
        return True
    
    def release(self):
        """释放执行许可"""
        try:
            self.semaphore.release()
        except ValueError:
            pass  # 防止重复释放
    
    def execute_with_retry(self, func, *args, **kwargs) -> Any:
        """
        执行函数，带自动重试
        
        Args:
            func: 要执行的函数
            *args, **kwargs: 函数参数
            
        Returns:
            函数返回值
            
        Raises:
            最后一次异常
        """
        last_exception = None
        
        for attempt in range(self.config.retry_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                with self._stats_lock:
                    self.stats["retry_attempts"] += 1
                
                # 判断是否应该重试
                if not self._should_retry(e):
                    break
                
                # 指数退避 + 随机抖动
                delay = self.config.retry_delay_base * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"[{self.name}] 请求失败 (尝试 {attempt+1}/{self.config.retry_attempts}): {e}")
                logger.info(f"[{self.name}] 等待 {delay:.1f}秒后重试...")
                time.sleep(delay)
        
        with self._stats_lock:
            self.stats["failed_requests"] += 1
        
        raise last_exception
    
    def _should_retry(self, exception: Exception) -> bool:
        """判断是否应该重试"""
        error_str = str(exception).lower()
        
        # 限流错误应该重试
        retryable_errors = [
            "rate limit", "too many requests", "429",
            "timeout", "connection", "temporary",
        ]
        
        for err in retryable_errors:
            if err in error_str:
                return True
        
        return False
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        with self._stats_lock:
            return self.stats.copy()


class RateLimiterManager:
    """
    统一限流管理器
    
    管理所有外部API服务的限流
    """
    
    # 默认配置 (从环境变量或配置文件中读取)
    DEFAULT_CONFIGS = {
        "deepseek": RateLimitConfig(
            rpm=60,           # DeepSeek较宽松
            concurrent=3,
            burst=10,
            retry_attempts=3,
            retry_delay_base=2.0,
        ),
        "pixabay": RateLimitConfig(
            rpm=100,          # 100 requests/min
            concurrent=5,
            burst=10,
            retry_attempts=3,
            retry_delay_base=1.0,
        ),
        "pexels": RateLimitConfig(
            rpm=3,            # 200/hour ≈ 3.3/min
            concurrent=2,
            burst=3,
            retry_attempts=3,
            retry_delay_base=2.0,
        ),
        "silicon_cloud": RateLimitConfig(
            rpm=30,           # 免费版30 RPM
            concurrent=2,
            burst=5,
            retry_attempts=3,
            retry_delay_base=1.0,
        ),
    }
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._limiters: Dict[str, ServiceRateLimiter] = {}
        self._init_from_config()
        self._initialized = True
        
        # 只打印一次初始化日志
        if not hasattr(RateLimiterManager, '_logged'):
            logger.info("限流管理器初始化完成")
            RateLimiterManager._logged = True
    
    def _init_from_config(self):
        """从配置初始化限流器"""
        import os
        
        for service, default_config in self.DEFAULT_CONFIGS.items():
            # 尝试从环境变量读取配置
            rpm_env = os.getenv(f"SELF_MEDIA_RATE_LIMIT_{service.upper()}_RPM")
            concurrent_env = os.getenv(f"SELF_MEDIA_RATE_LIMIT_{service.upper()}_CONCURRENT")
            
            config = RateLimitConfig(
                rpm=int(rpm_env) if rpm_env else default_config.rpm,
                concurrent=int(concurrent_env) if concurrent_env else default_config.concurrent,
                burst=default_config.burst,
                retry_attempts=default_config.retry_attempts,
                retry_delay_base=default_config.retry_delay_base,
            )
            
            self._limiters[service] = ServiceRateLimiter(service, config)
            logger.info(f"[{service}] 限流配置: {config.rpm} RPM, {config.concurrent} 并发")
    
    def get_limiter(self, service: str) -> ServiceRateLimiter:
        """获取指定服务的限流器"""
        if service not in self._limiters:
            raise ValueError(f"未知服务: {service}")
        return self._limiters[service]
    
    def acquire(self, service: str, timeout: Optional[float] = None) -> bool:
        """
        获取指定服务的执行许可
        
        Args:
            service: 服务名称
            timeout: 超时时间(秒)
            
        Returns:
            是否成功获取
        """
        limiter = self.get_limiter(service)
        return limiter.acquire(timeout)
    
    def release(self, service: str):
        """释放指定服务的执行许可"""
        limiter = self.get_limiter(service)
        limiter.release()
    
    def execute(self, service: str, func, *args, timeout: Optional[float] = None, **kwargs) -> Any:
        """
        在限流控制下执行函数
        
        Args:
            service: 服务名称
            func: 要执行的函数
            *args, **kwargs: 函数参数
            timeout: 获取许可的超时时间
            
        Returns:
            函数返回值
        """
        limiter = self.get_limiter(service)
        
        if not limiter.acquire(timeout):
            raise RuntimeError(f"[{service}] 无法获取执行许可，可能触发限流")
        
        try:
            return limiter.execute_with_retry(func, *args, **kwargs)
        finally:
            limiter.release()
    
    def get_all_stats(self) -> Dict[str, Dict[str, int]]:
        """获取所有服务的统计信息"""
        return {name: limiter.get_stats() for name, limiter in self._limiters.items()}
    
    def print_stats(self):
        """打印统计信息"""
        logger.info("=" * 50)
        logger.info("API限流统计")
        logger.info("=" * 50)
        
        for service, stats in self.get_all_stats().items():
            logger.info(f"\n[{service}]")
            logger.info(f"  总请求: {stats['total_requests']}")
            logger.info(f"  限流等待: {stats['throttled_requests']}")
            logger.info(f"  失败请求: {stats['failed_requests']}")
            logger.info(f"  重试次数: {stats['retry_attempts']}")


# 全局限流管理器实例
rate_limiter = RateLimiterManager()


# 便捷装饰器
def rate_limited(service: str, timeout: Optional[float] = None):
    """
    限流装饰器
    
    用法:
        @rate_limited("deepseek", timeout=30)
        def call_deepseek_api(...):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            return rate_limiter.execute(service, func, *args, timeout=timeout, **kwargs)
        return wrapper
    return decorator


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    # 测试令牌桶
    bucket = TokenBucket(rate=2, capacity=5)  # 每秒2个令牌，容量5
    
    print("测试令牌桶:")
    for i in range(10):
        if bucket.try_acquire():
            print(f"  请求 {i+1}: 成功")
        else:
            print(f"  请求 {i+1}: 失败，等待...")
            if bucket.acquire(timeout=1):
                print(f"  请求 {i+1}: 等待后成功")
            else:
                print(f"  请求 {i+1}: 超时")
    
    # 测试限流管理器
    print("\n测试限流管理器:")
    
    def mock_api_call(name):
        print(f"  调用API: {name}")
        time.sleep(0.1)
        return f"结果: {name}"
    
    # 快速调用测试
    for i in range(5):
        try:
            result = rate_limiter.execute("deepseek", mock_api_call, f"请求{i+1}")
            print(f"  {result}")
        except Exception as e:
            print(f"  错误: {e}")
    
    # 打印统计
    rate_limiter.print_stats()
