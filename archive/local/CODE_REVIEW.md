# 代码审查报告

> 审查日期: 2026-02-18
> 审查范围: step3_video, step5_subtitle, step6_translate, step7_merge

---

## 一、发现的问题

### 🔴 严重问题

#### 1. step6_translate.py - 翻译失败回退逻辑
**问题**: 当翻译API失败时，函数返回原文(英文)，导致竖排字幕显示英文
**位置**: `translate_batch()` 函数第256-257行
**建议**: 
- 添加重试机制
- 使用备用翻译API
- 标记未翻译内容而不是直接显示英文

#### 2. step3_video.py - 视频时长匹配精度
**问题**: 视频时长匹配使用 `required_duration * 2.0` 作为上限，可能导致视频过长
**位置**: 第442行
**建议**: 
- 减小上限倍数到1.5x
- 添加视频裁剪逻辑确保精确时长

#### 3. step7_merge.py - 音频时长探测失败处理
**问题**: 当ffprobe探测失败时，使用估计时长可能导致音视频不同步
**位置**: 第138-156行
**建议**: 
- 添加更多容错处理
- 使用WAV文件头直接读取时长(更快)

### 🟡 中等问题

#### 4. step5_subtitle.py - 简单SRT分割逻辑
**问题**: 长文本按字符数平均分割，可能切断单词
**位置**: 第114-135行
**建议**: 
- 使用更智能的分割算法(优先在标点处分割)
- 考虑语义完整性

#### 5. step6_translate.py - ASS时间精度
**问题**: 时间转换只保留2位小数(毫秒)，可能丢失精度
**位置**: `convert_time()` 函数第380-384行
**建议**: 
- 保留3位小数
- 使用更精确的时间格式

#### 6. step3_video.py - 关键词黑名单固定
**问题**: 黑名单是硬编码的，不够灵活
**位置**: 第426-433行
**建议**: 
- 从配置文件读取
- 支持动态更新

### 🟢 优化建议

#### 7. 性能优化 - TTS批量处理
**现状**: 已实现批量处理，但batch_size固定为2
**建议**: 
- 根据GPU显存动态调整batch_size
- 添加自适应逻辑

#### 8. 性能优化 - 视频下载
**现状**: 已实现异步下载
**建议**: 
- 添加下载进度显示
- 支持断点续传

#### 9. 用户体验 - 错误处理
**现状**: 部分错误只记录日志，用户无法感知
**建议**: 
- 添加更详细的错误提示
- 提供修复建议

#### 10. 代码质量 - 重复代码
**问题**: 多个step都有类似的文件路径处理逻辑
**建议**: 
- 提取到utils模块
- 统一路径处理

---

## 二、具体修复建议

### 修复1: 改进翻译失败处理

```python
# step6_translate.py
def translate_batch(texts):
    # ... 现有代码 ...
    
    # 出错时回退到原文 - 修改前
    # return texts
    
    # 修改后 - 使用备用方案
    logger.error("翻译失败，尝试备用方案...")
    
    # 方案1: 尝试简化后重新翻译
    simplified_texts = [t[:50] + "..." if len(t) > 50 else t for t in texts]
    # 重新尝试翻译简化版本...
    
    # 方案2: 标记为待翻译
    return [f"[需翻译] {text}" for text in texts]
```

### 修复2: 改进视频时长匹配

```python
# step3_video.py
# 修改前
max_duration = required_duration * 2.0

# 修改后
max_duration = required_duration * 1.5  # 更严格的上限
if max_duration > 45:  # 降低绝对上限
    max_duration = 45
```

### 修复3: 改进字幕分割

```python
# step5_subtitle.py
def smart_split_for_srt(text, max_chars=80):
    """智能分割文本，优先在标点处分割"""
    if len(text) <= max_chars:
        return [text]
    
    # 优先在句子结束标点处分割
    punctuations = ".!?。！？"
    mid = len(text) // 2
    
    # 在中点附近找最佳分割点
    best_split = mid
    min_dist = float('inf')
    
    for i in range(max(0, mid-20), min(len(text), mid+20)):
        if text[i] in punctuations:
            dist = abs(i - mid)
            if dist < min_dist:
                min_dist = dist
                best_split = i + 1
    
    return [text[:best_split].strip(), text[best_split:].strip()]
```

### 修复4: 改进时间精度

```python
# step6_translate.py
def convert_time(srt_time):
    # 修改前: 只保留2位小数
    # return f"{int(h)}:{m}:{s}.{ms[:2]}"
    
    # 修改后: 保留3位小数
    h, m, s_ms = srt_time.split(':')
    s, ms = s_ms.split(',')
    return f"{int(h)}:{m}:{s}.{ms[:3]}"
```

---

## 三、测试建议

1. **翻译失败场景测试**: 断开网络测试翻译失败时的行为
2. **长视频测试**: 测试30分钟以上的视频生成
3. **多片段测试**: 测试10+片段的视频同步
4. **边界情况测试**: 测试空内容、特殊字符等情况

---

## 四、优先级排序

| 优先级 | 问题 | 影响 |
|--------|------|------|
| P0 | 翻译失败回退逻辑 | 用户体验 |
| P1 | 视频时长匹配 | 视频质量 |
| P1 | 音频时长探测 | 音视频同步 |
| P2 | 字幕分割逻辑 | 字幕可读性 |
| P2 | 时间精度 | 字幕精度 |
| P3 | 关键词黑名单 | 搜索质量 |
