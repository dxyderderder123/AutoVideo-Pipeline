import os
import sys
from pathlib import Path

# 添加项目根目录到 sys.path，以便加载 .env
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

# 尝试加载 .env
def load_env():
    env_path = PROJECT_ROOT / '.env'
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

load_env()

# 配置常量
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
PEXELS_API_KEY = os.getenv('PEXELS_API_KEY')
PIXABAY_API_KEY = os.getenv('PIXABAY_API_KEY')
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# 路径配置
INPUT_DIR = PROJECT_ROOT / "workspace" / "input"
TEMP_BASE_DIR = PROJECT_ROOT / "workspace" / "temp"

# Finish Record File (Records processed videos)
FINISH_RECORD_FILE = PROJECT_ROOT / "workspace" / "finish.md"

# 测试开关 (优先读短名，回退读长名，兼容 .env 两种写法)
try:
    _limit_segments_env = (os.getenv("LIMIT_SEGMENTS") or os.getenv("SELF_MEDIA_LIMIT_SEGMENTS", "")).strip()
    LIMIT_SEGMENTS = int(_limit_segments_env) if _limit_segments_env else None
except Exception:
    LIMIT_SEGMENTS = None
VIDEO_SPEED_FACTOR = 1.0  # Video playback speed multiplier (1.0 = normal speed)  

# Video Resolution Standards (2026)
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30

# 视频编码参数 (Video Encoding Params)
VIDEO_BITRATE = "15M"  # 视频码率 (15Mbps, 适合4K/1080p高质量分发)
AUDIO_BITRATE = "192k" # 音频码率 (192kbps AAC, 标准高音质)

# NVENC 预设 (p1-p7, p1最快, p7质量最好)
# p1: 最快, p2: 较快, p3: 快, p4: 平衡, p5: 质量, p6: 更好质量, p7: 最好质量
_fast_mode = (os.getenv("FAST_MODE") or os.getenv("SELF_MEDIA_FAST_MODE", "0")).strip() == "1"
NVENC_PRESET = "p2" if _fast_mode else "p4"  # 快速模式使用p2, 正常模式使用p4

# TTS 批量大小 (增大可提升GPU利用率)
# 默认值根据GPU显存自动调整：8GB以下=2, 8-12GB=3, 12GB以上=4
def _get_default_tts_batch_size():
    try:
        import torch
        if torch.cuda.is_available():
            total_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            if total_mem >= 12:
                return 4
            elif total_mem >= 8:
                return 3
    except:
        pass
    return 2

TTS_BATCH_SIZE = int(os.getenv("SELF_MEDIA_TTS_BATCH_SIZE", str(_get_default_tts_batch_size())))

# 下载并发数 (增大可提升带宽利用率)
MAX_DOWNLOAD_CONCURRENCY = int(os.getenv("SELF_MEDIA_MAX_DOWNLOAD_CONCURRENCY", "5"))

# 封面生成配置 (Cover Generation)
SILICON_CLOUD_API_KEY = os.getenv("SILICON_CLOUD_API_KEY", "") # 从 .env 读取
COVER_MODEL = "Kwai-Kolors/Kolors" # 使用免费的 Kwai-Kolors 模型
COVER_PROMPT = "Abstract technology background, dark slate theme, glowing data lines, minimalist, high quality, 8k, no text"
COVER_FONT_PATH = "C:/Windows/Fonts/arialbd.ttf" # 默认使用 Arial Bold

# Debug/Cleanup Configuration
CLEANUP_TEMP_DIR = False  # Set to False to keep temp files for debugging

# 尾注配置 (End Note Configuration)
END_NOTE_ENABLE = True
END_NOTE_DURATION = 3.0    # 尾注时长 (秒)

# 尾注文字模板 (支持 {filename} 占位符)
# 使用三引号支持多行文本，格式自由调整
# 文字将自动居中显示，字体大小与英文字幕一致
END_NOTE_TEXT = """视频文稿来源于[扇贝阅读]APP | 短文 | 每日更新 | {filename}
视频素材来源于 pexels 和 Pixabay
"""

# 字体设置 (Windows 默认微软雅黑，防止中文乱码)
# 注意：ASS字幕渲染通常使用字体名称 (如 "Microsoft YaHei")，此路径主要备用
FONT_PATH = "C:/Windows/Fonts/msyh.ttc" 
FONT_COLOR = "white"       # 字体颜色

# 确保必要的目录存在
INPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_BASE_DIR.mkdir(parents=True, exist_ok=True)

# Bilibili Upload Configuration
# 上传开关：.env 中 ENABLE_UPLOAD=0 关闭, =1 开启
_enable_upload_env = (os.getenv("ENABLE_UPLOAD") or os.getenv("SELF_MEDIA_ENABLE_UPLOAD", "")).strip().lower()
if _enable_upload_env in {"0", "false", "no", "off"}:
    ENABLE_UPLOAD = False
elif _enable_upload_env in {"1", "true", "yes", "on"}:
    ENABLE_UPLOAD = True
else:
    ENABLE_UPLOAD = False  # 默认关闭，安全第一
BILIBILI_SESSDATA = os.getenv('BILIBILI_SESSDATA', '')
BILIBILI_BILI_JCT = os.getenv('BILIBILI_BILI_JCT', '')
BILIBILI_BUVID3 = os.getenv('BILIBILI_BUVID3', '')
BILIBILI_DEDEUSERID = os.getenv('BILIBILI_DEDEUSERID', '')
BILIBILI_TAGS = ["AI", "Tech", "Automation", "Python"] # Default tags

# Bilibili Collection Mapping (Rule-based)
# Format: {"Keyword": Collection_ID}
# If the input document's filename or title contains the keyword (case-insensitive),
# it will be added to the corresponding collection.
# Example: {"News": 12345, "Tutorial": 67890}
BILIBILI_COLLECTION_RULES = {
    "1初阶": 7349139,      # 合集·初阶（高考）
    "2中阶": 7349156,      # 合集·中阶（四级）
    "3中高阶": 7349169,    # 合集·中高阶（六级/考研）
    "4高阶": 7349182,      # 合集·高阶（雅思）
    "5精通": 7349195,      # 合集·精通（专八）
}

# =============================================================================
# 优化配置 (Optimization Settings)
# =============================================================================

# --- API限流配置 ---
# 各服务的RPM限制 (Requests Per Minute)
RATE_LIMIT_DEEPSEEK_RPM = int(os.getenv("SELF_MEDIA_RATE_LIMIT_DEEPSEEK_RPM", "60"))
RATE_LIMIT_PIXABAY_RPM = int(os.getenv("SELF_MEDIA_RATE_LIMIT_PIXABAY_RPM", "100"))
RATE_LIMIT_PEXELS_RPM = int(os.getenv("SELF_MEDIA_RATE_LIMIT_PEXELS_RPM", "3"))  # 200/hour ≈ 3/min
RATE_LIMIT_SILICON_RPM = int(os.getenv("SELF_MEDIA_RATE_LIMIT_SILICON_RPM", "30"))

# 各服务的并发限制
RATE_LIMIT_DEEPSEEK_CONCURRENT = int(os.getenv("SELF_MEDIA_RATE_LIMIT_DEEPSEEK_CONCURRENT", "3"))
RATE_LIMIT_PIXABAY_CONCURRENT = int(os.getenv("SELF_MEDIA_RATE_LIMIT_PIXABAY_CONCURRENT", "5"))
RATE_LIMIT_PEXELS_CONCURRENT = int(os.getenv("SELF_MEDIA_RATE_LIMIT_PEXELS_CONCURRENT", "2"))
RATE_LIMIT_SILICON_CONCURRENT = int(os.getenv("SELF_MEDIA_RATE_LIMIT_SILICON_CONCURRENT", "2"))

# --- 硬件控制配置 ---
# GPU显存使用阈值 (0.0-1.0)，超过此值将拒绝新任务
GPU_MEMORY_THRESHOLD = float(os.getenv("SELF_MEDIA_GPU_MEMORY_THRESHOLD", "0.9"))

# CPU使用率阈值 (0.0-1.0)
CPU_USAGE_THRESHOLD = float(os.getenv("SELF_MEDIA_CPU_USAGE_THRESHOLD", "0.8"))

# 字幕生成是否使用GPU (0=禁用, 1=启用)
SUBTITLE_USE_GPU = os.getenv("SELF_MEDIA_SUBTITLE_USE_GPU", "0").strip() == "1"

# --- 下载配置 ---
# 最大并发下载数
MAX_DOWNLOAD_CONCURRENCY = int(os.getenv("SELF_MEDIA_MAX_DOWNLOAD_CONCURRENCY", "5"))

# 下载带宽限制 (MB/s)，None表示无限制
DOWNLOAD_BANDWIDTH_LIMIT_MBPS = os.getenv("SELF_MEDIA_DOWNLOAD_BANDWIDTH_LIMIT_MBPS")
if DOWNLOAD_BANDWIDTH_LIMIT_MBPS:
    DOWNLOAD_BANDWIDTH_LIMIT_MBPS = float(DOWNLOAD_BANDWIDTH_LIMIT_MBPS)

# --- 快速模式配置 ---
# TTS推理步数 (2-12，越小越快但质量可能下降)
TTS_INFERENCE_STEPS_FAST = int(os.getenv("SELF_MEDIA_TTS_STEPS_FAST", "4"))
TTS_INFERENCE_STEPS_NORMAL = int(os.getenv("SELF_MEDIA_TTS_STEPS_NORMAL", "6"))

# 草稿预览模式 (生成480p低质量视频用于快速验证)
PREVIEW_MODE = (os.getenv("PREVIEW_MODE") or os.getenv("SELF_MEDIA_PREVIEW_MODE", "0")).strip() == "1"

# 视频预览分辨率
PREVIEW_WIDTH = 854
PREVIEW_HEIGHT = 480
