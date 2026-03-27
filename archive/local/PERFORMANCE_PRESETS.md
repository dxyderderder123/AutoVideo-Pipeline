# 性能与质量的最佳平衡（推荐设置）

目标：不明显牺牲质量的前提下，尽量减少卡顿、并让重复生成更快。

## 你现在“变慢/变卡”的主要原因
- 现在是全文分段，段数比以前多 → TTS 推理次数 + 素材下载次数显著增加
- TTS/对齐/编码会把 GPU 打满一段时间，桌面也用 GPU，所以会有卡顿

## 关键改进（已内置）
- 默认分段更“粗”一些（减少段数但仍保持可读/可配字幕）
- TTS 支持音频缓存：同一段文本/同一配置再跑会直接复用 wav，几乎不占 GPU

缓存位置：workspace/cache/tts_cache

## 推荐预设 A：质量优先 + 尽量不卡顿（推荐）
适用：你要“看起来像以前那么顺”，同时字幕对齐保持 WhisperX（质量不降）。

环境变量：
- SELF_MEDIA_TTS_STEPS=6
- SELF_MEDIA_WHISPERX_DEVICE=cpu
- SELF_MEDIA_VIDEO_DOWNLOAD_WORKERS=2
- SELF_MEDIA_ENABLE_UPLOAD=0（调试期避免误传）

说明：
- WhisperX 用 CPU 只影响速度，不影响对齐质量；同时避免它抢 GPU 造成桌面卡顿
- TTS 仍用 GPU，但因为有缓存，你在反复调参/修 bug 的二次运行会非常快

## 推荐预设 B：质量优先 + 更快（会更卡）
适用：你不介意生成时电脑卡一点，但想尽快出片。

- SELF_MEDIA_TTS_STEPS=6
- SELF_MEDIA_WHISPERX_DEVICE=cuda
- SELF_MEDIA_VIDEO_DOWNLOAD_WORKERS=3

## 推荐预设 C：最低卡顿（速度会明显变慢）
适用：你一边办公一边跑，不想桌面卡。

- SELF_MEDIA_TTS_DEVICE=cpu
- SELF_MEDIA_WHISPERX_DEVICE=cpu

## 提示
- 第一次生成某篇新文章：TTS 缓存是“冷启动”，必然会比较慢；从第二次开始收益很大
- 如果你觉得段数仍然偏多/偏少，再考虑设置 SELF_MEDIA_TARGET_SEGMENTS（建议 8~12），但一般不必固定
