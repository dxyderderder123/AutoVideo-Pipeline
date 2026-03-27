#!/usr/bin/env python3
"""
异步下载管理器

提供高性能的异步并发下载功能，支持：
- 自适应并发控制
- 断点续传
- 下载进度统计
- 带宽限制保护
"""

import os
import time
import asyncio
import aiohttp
import aiofiles
import logging
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class DownloadTask:
    """下载任务定义"""
    url: str
    output_path: Path
    task_id: str = field(default="")
    headers: Dict[str, str] = field(default_factory=dict)
    chunk_size: int = 8192
    timeout: int = 60
    retries: int = 3
    retry_delay: float = 1.0
    
    def __post_init__(self):
        if not self.task_id:
            # 使用URL哈希作为任务ID
            self.task_id = hashlib.md5(self.url.encode()).hexdigest()[:8]


@dataclass
class DownloadResult:
    """下载结果"""
    task: DownloadTask
    success: bool
    error: Optional[str] = None
    downloaded_bytes: int = 0
    duration: float = 0.0
    speed_mbps: float = 0.0


class AsyncDownloader:
    """
    异步下载管理器
    
    使用aiohttp实现高性能并发下载
    """
    
    def __init__(
        self,
        max_concurrency: int = 5,
        bandwidth_limit_mbps: Optional[float] = None,
        connection_timeout: int = 30,
        read_timeout: int = 60,
        min_speed_mbps: float = 0.5,  # 最小下载速度(MB/s)，低于此速度视为慢速
        slow_speed_timeout: int = 30   # 慢速下载超时(秒)，超过此时间中断
    ):
        """
        Args:
            max_concurrency: 最大并发下载数
            bandwidth_limit_mbps: 带宽限制(MB/s)，None表示无限制
            connection_timeout: 连接超时(秒)
            read_timeout: 读取超时(秒)
            min_speed_mbps: 最小下载速度(MB/s)，低于此速度视为慢速
            slow_speed_timeout: 慢速下载超时(秒)，超过此时间中断
        """
        self.max_concurrency = max_concurrency
        self.bandwidth_limit_mbps = bandwidth_limit_mbps
        self.connection_timeout = connection_timeout
        self.read_timeout = read_timeout
        self.min_speed_mbps = min_speed_mbps
        self.slow_speed_timeout = slow_speed_timeout
        
        # 信号量控制并发
        self._semaphore = asyncio.Semaphore(max_concurrency)
        
        # 统计
        self._stats = {
            "total_tasks": 0,
            "success": 0,
            "failed": 0,
            "total_bytes": 0,
            "total_duration": 0.0,
        }
        
        # 进度回调
        self._progress_callback: Optional[Callable] = None
        
        logger.info(f"异步下载管理器初始化: 最大并发={max_concurrency}")
    
    def set_progress_callback(self, callback: Callable[[str, int, int], None]):
        """
        设置进度回调函数
        
        Args:
            callback: 回调函数(task_id, downloaded, total)
        """
        self._progress_callback = callback
    
    async def _download_with_session(
        self,
        session: aiohttp.ClientSession,
        task: DownloadTask
    ) -> DownloadResult:
        """
        使用session执行下载
        
        Args:
            session: aiohttp session
            task: 下载任务
            
        Returns:
            下载结果
        """
        start_time = time.time()
        downloaded = 0
        
        # 确保输出目录存在
        task.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 临时文件路径
        temp_path = task.output_path.with_suffix('.tmp')
        
        for attempt in range(task.retries):
            try:
                async with self._semaphore:
                    logger.info(f"[{task.task_id}] 开始下载: {task.url}")
                    
                    async with session.get(
                        task.url,
                        headers=task.headers,
                        timeout=aiohttp.ClientTimeout(
                            connect=self.connection_timeout,
                            sock_read=self.read_timeout
                        )
                    ) as response:
                        response.raise_for_status()
                        
                        # 获取文件大小
                        total_size = int(response.headers.get('content-length', 0))
                        
                        # 异步写入文件
                        async with aiofiles.open(temp_path, 'wb') as f:
                            last_check_time = time.time()
                            last_downloaded = 0
                            slow_speed_start = None
                            
                            async for chunk in response.content.iter_chunked(task.chunk_size):
                                await f.write(chunk)
                                downloaded += len(chunk)
                                current_time = time.time()
                                
                                # 每5秒检查一次下载速度
                                if current_time - last_check_time >= 5:
                                    speed_mbps = ((downloaded - last_downloaded) / (1024 * 1024)) / (current_time - last_check_time)
                                    
                                    # 检查是否慢速
                                    if speed_mbps < self.min_speed_mbps:
                                        if slow_speed_start is None:
                                            slow_speed_start = current_time
                                            logger.warning(f"[{task.task_id}] 下载速度过慢: {speed_mbps:.2f}MB/s，开始计时...")
                                        elif current_time - slow_speed_start > self.slow_speed_timeout:
                                            # 慢速超时，中断下载
                                            raise asyncio.TimeoutError(
                                                f"下载速度过慢({speed_mbps:.2f}MB/s)持续{self.slow_speed_timeout}秒，中断下载"
                                            )
                                    else:
                                        # 速度恢复正常，重置计时
                                        if slow_speed_start is not None:
                                            logger.info(f"[{task.task_id}] 下载速度恢复: {speed_mbps:.2f}MB/s")
                                        slow_speed_start = None
                                    
                                    last_check_time = current_time
                                    last_downloaded = downloaded
                                
                                # 进度回调
                                if self._progress_callback:
                                    self._progress_callback(task.task_id, downloaded, total_size)
                                
                                # 带宽限制
                                if self.bandwidth_limit_mbps:
                                    await self._apply_bandwidth_limit(len(chunk))
                
                # 下载成功，移动到最终位置
                if temp_path.exists():
                    if task.output_path.exists():
                        task.output_path.unlink()
                    temp_path.rename(task.output_path)
                
                duration = time.time() - start_time
                speed = (downloaded / (1024 * 1024)) / duration if duration > 0 else 0
                
                logger.info(f"[{task.task_id}] 下载完成: {task.output_path.name} "
                          f"({downloaded/1024/1024:.1f}MB, {speed:.1f}MB/s)")
                
                return DownloadResult(
                    task=task,
                    success=True,
                    downloaded_bytes=downloaded,
                    duration=duration,
                    speed_mbps=speed
                )
                
            except Exception as e:
                logger.warning(f"[{task.task_id}] 下载失败 (尝试 {attempt+1}/{task.retries}): {e}")
                
                if attempt < task.retries - 1:
                    await asyncio.sleep(task.retry_delay * (2 ** attempt))
                else:
                    # 所有重试失败
                    if temp_path.exists():
                        temp_path.unlink()
                    
                    return DownloadResult(
                        task=task,
                        success=False,
                        error=str(e),
                        downloaded_bytes=downloaded,
                        duration=time.time() - start_time
                    )
    
    async def _apply_bandwidth_limit(self, chunk_size: int):
        """应用带宽限制"""
        if not self.bandwidth_limit_mbps:
            return
        
        # 计算应该等待的时间
        chunk_time = chunk_size / (self.bandwidth_limit_mbps * 1024 * 1024)
        await asyncio.sleep(chunk_time)
    
    async def download(self, task: DownloadTask) -> DownloadResult:
        """
        下载单个文件
        
        Args:
            task: 下载任务
            
        Returns:
            下载结果
        """
        # 创建session
        connector = aiohttp.TCPConnector(
            limit=self.max_concurrency * 2,
            limit_per_host=self.max_concurrency,
            enable_cleanup_closed=True,
            force_close=True,
        )
        
        timeout = aiohttp.ClientTimeout(
            connect=self.connection_timeout,
            sock_read=self.read_timeout
        )
        
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        ) as session:
            return await self._download_with_session(session, task)
    
    async def download_many(
        self,
        tasks: List[DownloadTask],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[DownloadResult]:
        """
        并发下载多个文件
        
        Args:
            tasks: 下载任务列表
            progress_callback: 整体进度回调(已完成数, 总数)
            
        Returns:
            下载结果列表
        """
        if not tasks:
            return []
        
        self._stats["total_tasks"] += len(tasks)
        
        # 创建共享session
        connector = aiohttp.TCPConnector(
            limit=self.max_concurrency * 2,
            limit_per_host=self.max_concurrency,
            enable_cleanup_closed=True,
            force_close=True,
        )
        
        timeout = aiohttp.ClientTimeout(
            connect=self.connection_timeout,
            sock_read=self.read_timeout
        )
        
        results = []
        completed = 0
        
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        ) as session:
            # 创建任务
            async def download_with_progress(task: DownloadTask) -> DownloadResult:
                nonlocal completed
                result = await self._download_with_session(session, task)
                completed += 1
                
                if progress_callback:
                    progress_callback(completed, len(tasks))
                
                return result
            
            # 并发执行
            download_tasks = [download_with_progress(task) for task in tasks]
            results = await asyncio.gather(*download_tasks, return_exceptions=True)
            
            # 处理异常结果
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    processed_results.append(DownloadResult(
                        task=tasks[i],
                        success=False,
                        error=str(result)
                    ))
                    self._stats["failed"] += 1
                else:
                    processed_results.append(result)
                    if result.success:
                        self._stats["success"] += 1
                        self._stats["total_bytes"] += result.downloaded_bytes
                        self._stats["total_duration"] += result.duration
                    else:
                        self._stats["failed"] += 1
            
            return processed_results
    
    def download_sync(self, url: str, output_path: Path, **kwargs) -> DownloadResult:
        """
        同步接口：下载单个文件
        
        Args:
            url: 下载URL
            output_path: 输出路径
            **kwargs: 其他参数
            
        Returns:
            下载结果
        """
        task = DownloadTask(url=url, output_path=output_path, **kwargs)
        return asyncio.run(self.download(task))
    
    def download_many_sync(
        self,
        urls: List[str],
        output_dir: Path,
        filenames: Optional[List[str]] = None,
        **kwargs
    ) -> List[DownloadResult]:
        """
        同步接口：并发下载多个文件
        
        Args:
            urls: URL列表
            output_dir: 输出目录
            filenames: 文件名列表(可选，默认从URL提取)
            **kwargs: 其他参数
            
        Returns:
            下载结果列表
        """
        tasks = []
        for i, url in enumerate(urls):
            if filenames and i < len(filenames):
                filename = filenames[i]
            else:
                # 从URL提取文件名
                parsed = urlparse(url)
                filename = os.path.basename(parsed.path) or f"download_{i}"
            
            task = DownloadTask(
                url=url,
                output_path=output_dir / filename,
                **kwargs
            )
            tasks.append(task)
        
        return asyncio.run(self.download_many(tasks))
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = self._stats.copy()
        
        if stats["total_duration"] > 0:
            stats["avg_speed_mbps"] = (
                (stats["total_bytes"] / (1024 * 1024)) / stats["total_duration"]
            )
        else:
            stats["avg_speed_mbps"] = 0
        
        stats["total_mb"] = stats["total_bytes"] / (1024 * 1024)
        
        return stats
    
    def print_stats(self):
        """打印统计信息"""
        stats = self.get_stats()
        
        logger.info("=" * 50)
        logger.info("下载统计")
        logger.info("=" * 50)
        logger.info(f"总任务: {stats['total_tasks']}")
        logger.info(f"成功: {stats['success']}")
        logger.info(f"失败: {stats['failed']}")
        logger.info(f"总下载: {stats['total_mb']:.1f}MB")
        logger.info(f"平均速度: {stats['avg_speed_mbps']:.1f}MB/s")


class AdaptiveDownloader(AsyncDownloader):
    """
    自适应下载管理器
    
    根据网络状况动态调整并发数
    """
    
    def __init__(
        self,
        min_concurrency: int = 2,
        max_concurrency: int = 10,
        target_speed_mbps: float = 5.0,
        **kwargs
    ):
        """
        Args:
            min_concurrency: 最小并发数
            max_concurrency: 最大并发数
            target_speed_mbps: 目标下载速度(MB/s)
        """
        super().__init__(max_concurrency=min_concurrency, **kwargs)
        
        self.min_concurrency = min_concurrency
        self.max_concurrency = max_concurrency
        self.target_speed_mbps = target_speed_mbps
        
        # 速度历史
        self._speed_history: List[float] = []
        self._history_max_size = 10
    
    def _update_concurrency(self, speed_mbps: float):
        """根据速度更新并发数"""
        self._speed_history.append(speed_mbps)
        
        if len(self._speed_history) > self._history_max_size:
            self._speed_history.pop(0)
        
        if len(self._speed_history) < 3:
            return
        
        avg_speed = sum(self._speed_history) / len(self._speed_history)
        current_concurrency = self.max_concurrency
        
        # 如果速度低于目标，增加并发
        if avg_speed < self.target_speed_mbps * 0.8:
            new_concurrency = min(current_concurrency + 1, self.max_concurrency)
            if new_concurrency != current_concurrency:
                logger.info(f"增加并发数: {current_concurrency} -> {new_concurrency}")
                self.max_concurrency = new_concurrency
                self._semaphore = asyncio.Semaphore(new_concurrency)
        
        # 如果速度很高，可以适当减少并发
        elif avg_speed > self.target_speed_mbps * 1.5:
            new_concurrency = max(current_concurrency - 1, self.min_concurrency)
            if new_concurrency != current_concurrency:
                logger.info(f"减少并发数: {current_concurrency} -> {new_concurrency}")
                self.max_concurrency = new_concurrency
                self._semaphore = asyncio.Semaphore(new_concurrency)


# 全局下载器实例 (从环境变量读取配置)
_downloader_instance = None

def create_downloader() -> AsyncDownloader:
    """创建配置好的下载器"""
    import os
    
    # 读取配置
    max_concurrency = int(os.getenv("SELF_MEDIA_MAX_DOWNLOAD_CONCURRENCY", "5"))
    bandwidth_limit = os.getenv("SELF_MEDIA_DOWNLOAD_BANDWIDTH_LIMIT_MBPS")
    
    kwargs = {
        "max_concurrency": max_concurrency,
    }
    
    if bandwidth_limit:
        kwargs["bandwidth_limit_mbps"] = float(bandwidth_limit)
    
    return AsyncDownloader(**kwargs)


def get_downloader() -> AsyncDownloader:
    """获取全局下载器实例 (单例)"""
    global _downloader_instance
    if _downloader_instance is None:
        _downloader_instance = create_downloader()
    return _downloader_instance


# 默认下载器实例 (延迟初始化避免导入时日志重复)
downloader = None

def _init_downloader():
    """初始化全局下载器"""
    global downloader
    if downloader is None:
        downloader = get_downloader()
    return downloader


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    # 测试下载器
    test_downloader = AsyncDownloader(max_concurrency=3)
    
    # 测试单文件下载
    test_url = "https://www.w3schools.com/html/mov_bbb.mp4"
    test_output = Path("test_download.mp4")
    
    print(f"\n测试单文件下载:")
    print(f"  URL: {test_url}")
    print(f"  输出: {test_output}")
    
    result = test_downloader.download_sync(test_url, test_output)
    
    print(f"\n结果:")
    print(f"  成功: {result.success}")
    print(f"  大小: {result.downloaded_bytes / 1024:.1f}KB")
    print(f"  速度: {result.speed_mbps:.1f}MB/s")
    
    if result.error:
        print(f"  错误: {result.error}")
    
    # 清理
    if test_output.exists():
        test_output.unlink()
    
    # 打印统计
    test_downloader.print_stats()
