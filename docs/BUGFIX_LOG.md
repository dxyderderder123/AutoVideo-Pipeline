# Bug 修复日志

本文档记录 Bug 修复、技术债清理及流程改进，旨在确保项目的长期可维护性并防止问题回归。

## 2026-02-03: TTS 进程挂起 (TTS Process Hanging)

### 问题描述
**症状**：运行 `step2_tts.py` 时，进程在生成第一个片段时无限挂起（进度条停留在 0%），无报错信息，但在任务管理器中显示 GPU/CPU 占用极低。
**根因**：使用了系统全局 Python 环境运行脚本，而非项目专用的虚拟环境 (`venv`)。全局环境中的 PyTorch/CUDA 版本与 VibeVoice 要求的特定版本（尤其是 `flash-attn` 或 `sdpa` 实现）不兼容，导致底层推理线程死锁。

### 修复方案
**严格环境隔离**：
1. 强制所有运行命令显式调用虚拟环境解释器：`v:\Default\Desktop\Self-media\venv\Scripts\python.exe`。
2. 在 Core Memory 中添加了 CRITICAL 规则，禁止使用全局 `python` 命令。

### 状态
- [x] 已验证 (test_20260203_173758 恢复正常运行)

---

## 2026-02-03: 字幕重叠与跳动 (Subtitle Overlap & Jitter)

### 问题描述
**症状**：字幕（尤其是中文字幕）偶尔会出现跳动，或出现在非预期的位置（如屏幕顶部、屏幕外）。
**根因**：WhisperX/Wav2Vec2 对齐模型偶尔会生成重叠的时间戳（例如：上一句在 20.420秒 结束，下一句却在 20.399秒 开始）。这 20毫秒 的重叠导致 ASS 渲染器（以及 FFmpeg）为了避免文字碰撞，强制改变布局，导致视觉上的“乱跑”。

### 修复方案
在对齐后处理逻辑中加入了“防碰撞（Collision Prevention）”机制。
- **文件**: `tools/WhisperX/align.py`
- **逻辑**: 
  ```python
  if start_time < prev_end:
      # 将上一句的结束时间强制提前到当前句开始时间的前 1毫秒
      new_prev_end = max(all_lines[-1]['start'], start_time - 0.001)
      all_lines[-1]['end'] = new_prev_end
  ```
- **结果**: 实现零重叠，字幕位置稳定。

### 状态
- [x] 已验证 (test_20260202_210632)

---

## 2026-02-03: 中文字幕缺失 (Missing Chinese Subtitles)

### 问题描述
**症状**：最终视频包含英文字幕，但缺少中文字幕。
**根因**: 
1. 为了节省 Token 或调试时间，`main.py` 中的 `step5_1_translate.py` 调用被注释掉了。
2. DeepSeek API 偶尔返回的翻译行数少于源行数（Key Mismatch），导致脚本报错崩溃或跳过写入。

### 修复方案
1. **流程**: 在 `main.py` 中重新启用了 `step5_1_translate.py`。
2. **健壮性**: 在 `step5_1_translate.py` 中添加了兜底逻辑，当遇到缺失的 Key 时，自动插入空字符串而不是直接报错。
- **文件**: `test/workflow_v1/main.py`, `test/workflow_v1/step5_1_translate.py`

### 状态
- [x] 已验证

---

## 2026-02-03: 字幕定位与4K适配 (Subtitle Positioning for 4K)

### 问题描述
**症状**：在 4K 分辨率下，字幕过大、描边过粗，或显示在屏幕外。
**根因**: 使用了硬编码的像素值，或基于 1080p 的相对比例在 4K (3840x2160) 下表现不佳。

### 修复方案
改为基于 `video_h` (2160p) 的精细化相对比例缩放。
- **文件**: `step6_merge.py` (英文), `step5_1_translate.py` (中文)
- **设置**:
  - **英文**: 字体大小 4% (86px), 描边 0.2% (4px), 底部边距 5.5%。
  - **中文**: 字体大小 3.5% (75px), 对齐方式 6 (右下角), 垂直边距 5.5%。

### 状态
- [x] 已验证

---

## 2026-02-03: WhisperX 导入错误 (WhisperX Import Error)

### 问题描述
**症状**：运行 `step5_subtitle.py` 时报错 `ModuleNotFoundError: No module named 'whisperx'`。
**根因**: 脚本使用的是全局 Python 环境，而非项目专用的虚拟环境 (`venv`)。

### 修复方案
强制指定 venv解释器的绝对路径: `v:\Default\Desktop\Self-media\venv\Scripts\python.exe`。

### 状态
- [x] 已验证
