# 全自动化视频生成工作流设计文档 (2025 H2 Edition)

## 1. 核心理念 (Core Philosophy)
-   **执行者模式**: AI Agent 作为严格执行者，不进行发散性创新。
-   **数据完整性**: 视频画面必须严格服务于数据逻辑，拒绝装饰性失真。
-   **极简主义美学**: Modern Tech/SaaS 风格，Slate/Zinc 色调，无冗余装饰。
-   **2025+ 技术栈**: 全面采用 2025 年下半年及以后的前沿技术 (DeepSeek V3, VibeVoice, MMAudio, WhisperX)。
-   **1080p 标准化**: 全流程对齐 1920x1080 分辨率，平衡画质与移动端分发效率。

## 2. 管道架构 (Pipeline Architecture)

### 第一步：深度语义分析 (`src/step1_analyze.py`)
-   **引擎**: DeepSeek V3 (API)
-   **功能**:
    -   **语义分镜**: 将文案切分为 10-20 秒的语义完整片段 (2-4 个完整句子)。
    -   **关键词提取**: 为每个分镜生成精准的英文视频搜索关键词 (Pexels/Pixabay Keywords)。
    -   **音效提示词**: 生成物理环境音效提示词 (Sound Prompts)，严格排除人声。
-   **输出**: `analysis.json`

### 第二步：高保真语音合成 (`src/step2_tts.py`)
-   **引擎**: VibeVoice (2025 SOTA)
-   **配置**:
    -   参考音频: `assets/voice/reference.wav` (高保真克隆)。
    -   参数: `cfg_scale=1.5` (高保真), `temperature=0.7` (自然度), 禁用 `repetition_penalty`。
-   **输出**: `tts/{id}.wav` (WAV 格式)

### 第三步：混合视频源获取 (`src/step3_video.py`)
-   **源**: Pexels API (主) + Pixabay API (备选)
-   **策略**:
    -   **稳定性过滤**: 强制添加 "tripod", "slow motion", "cinematic", "4k" 等关键词，过滤手持晃动镜头。
    -   **1080p 优选**: 优先获取 1080p (FullHD) 视频，避免 4K 资源浪费，提升处理速度。
    -   **API 级联**: Pexels 搜索失败或无结果时，自动回退至 Pixabay 进行搜索。
-   **输出**: `video/{id}.mp4`

### 第四步：精准字幕强制对齐 (`src_english/step5_subtitle.py`)
-   **工具**: WhisperX (Wav2Vec2 Forced Alignment)
-   **策略**:
    -   **强制对齐**: 利用 Wav2Vec2 模型将已知文本强制对齐到音频时间轴，消除 STT 识别错误。
    -   **智能断句**: 基于标点符号的回溯断句逻辑 (Smart Segmentation)，避免孤儿词。
    -   **防碰撞机制**: 自动检测并修复时间轴重叠 (Collision Prevention)，确保字幕不闪烁。
-   **输出**: `output/subtitles.srt` (SRT 字幕文件)

### 第五步：中文字幕翻译与排版 (`src_english/step6_translate.py`)
-   **引擎**: DeepSeek V3 (API)
-   **策略**:
    -   **1:1 对齐翻译**: 保持与英文字幕行数和时间轴完全一致。
    -   **ASS 排版**: 生成 `.ass` 特效字幕。
        -   **布局**: 右侧竖排 (Vertical)，Modern SaaS 风格。
        -   **分辨率**: 严格对齐 1920x1080 画布 (PlayResX/Y)。
        -   **样式**: 75px 字体 (3.5% Video Height)，细描边，底部对齐。
-   **输出**: `output/subtitles_zh.ass`

### 第六步：专业混音与合成 (`src_english/step7_merge.py`)
-   **工具**: FFmpeg (NVENC Hardware Acceleration)
-   **配置**:
    -   **编码器**: `h264_nvenc` (NVIDIA GPU 加速)。
    -   **码率**: 15M (适合 1080p 高质量分发)。
    -   **字幕烧录**: 同时烧录底部英文 SRT 和右侧竖排中文 ASS。
-   **输出**: `output/final_video.mp4`

### 第七步：封面生成 (`src_english/step8_cover.py`)
-   **引擎**: SiliconCloud (Kwai-Kolors 模型)
-   **策略**:
    -   DeepSeek生成上下文感知的极简线条艺术风格提示词。
    -   Kolors生成封面底图。
    -   PIL添加标题文字，输出横版(4:3)和竖版(9:16)两种格式。
-   **输出**: `{filename}_horizontal.jpg`, `{filename}_vertical.jpg`

### 第八步：Bilibili上传 (`src_english/step9_upload.py`)
-   **库**: bilibili-api-python
-   **功能**:
    -   视频上传。
    -   自动添加到对应合集 (基于文件名/内容匹配)。
    -   支持重试机制和错误处理。
-   **输出**: 上传成功后的Bilibili视频链接

## 3. 目录结构 (Directory Structure)
```
v:\Default\Desktop\Self-media\
├── main.py                    # 项目统一入口 (Entry Point)
├── batch_run.py               # 批量处理入口
├── src_english\               # 核心源码 (Core Source)
│   ├── config.py              # 配置中心
│   ├── workflow.py            # 流程控制器
│   ├── step1_analyze.py       # 语义分析
│   ├── step2_tts.py           # 语音合成
│   ├── step3_video.py         # 视频获取 (Pexels/Pixabay)
│   ├── step5_subtitle.py      # 字幕对齐
│   ├── step6_translate.py     # 翻译排版
│   ├── step7_merge.py         # 合成渲染
│   ├── step8_cover.py         # 封面生成
│   ├── step9_upload.py        # Bilibili上传
│   ├── utils_lock.py          # 并发锁工具
│   ├── utils_rate_limiter.py  # API限流管理器
│   ├── utils_hardware.py      # 硬件监控调度器
│   └── utils_downloader.py    # 异步下载管理器
├── tools\                     # 外部工具
│   ├── WhisperX\              # 字幕对齐工具
│   └── vibevoice\             # VibeVoice语音合成
├── workspace\                 # 工作区
│   ├── input\                 # 用户输入 (MD/TXT)
│   └── temp\                  # 临时处理目录
│       └── [Project_ID]\
│           ├── analysis.json
│           ├── tts\
│           ├── video\
│           └── output\
├── docs\                      # 项目文档
│   ├── BUGFIX_LOG.md          # Bug 修复记录
│   └── OPTIMIZATION_LOG.md    # 优化记录
├── .env                       # 环境变量 (API Keys)
└── workflow_design.md         # 本文档
```

## 4. 关键约束 (Key Constraints)
-   **环境隔离**: 所有 Python 脚本必须在 `venv` 虚拟环境中运行。
-   **信息时效**: 仅使用 2025 年 6 月以后的技术文档和库版本。
-   **音频格式**: 统一使用 `.wav` 以保证兼容性。
-   **分辨率**: 全流程统一使用 **1920x1080**。

## 5. 优化特性 (Optimization Features)

### 5.1 API限流保护
-   **统一限流管理器**: 自动管理DeepSeek/Pixabay/Pexels/SiliconCloud的API调用速率。
-   **令牌桶算法**: 防止触发服务商限额墙。
-   **自动退避重试**: 遇到限流自动等待后重试。

### 5.2 硬件负载均衡
-   **GPU显存监控**: 实时监控显存使用，防止OOM。
-   **任务优先级队列**: GPU任务串行化，CPU任务并行化。
-   **自适应并发**: 根据硬件负载动态调整并发数。

### 5.3 异步IO优化
-   **并发视频下载**: 使用aiohttp实现并行下载，最大化带宽利用。
-   **断点续传**: 支持下载中断后恢复。
-   **带宽限制**: 可选限制下载速度，避免影响其他网络应用。

### 5.4 环境变量配置
```bash
# API限流
SELF_MEDIA_RATE_LIMIT_DEEPSEEK_RPM=60
SELF_MEDIA_RATE_LIMIT_PIXABAY_RPM=100
SELF_MEDIA_RATE_LIMIT_PEXELS_RPM=3
SELF_MEDIA_RATE_LIMIT_SILICON_RPM=30

# 硬件控制
SELF_MEDIA_GPU_MEMORY_THRESHOLD=0.9
SELF_MEDIA_MAX_DOWNLOAD_CONCURRENCY=5
SELF_MEDIA_SUBTITLE_USE_GPU=0

# 快速模式
SELF_MEDIA_FAST_MODE=1
SELF_MEDIA_PREVIEW_MODE=0
```
