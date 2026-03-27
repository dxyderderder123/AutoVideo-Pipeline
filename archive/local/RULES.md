## 工作规则
- 任何影响结果的改动必须用 run_batch.bat 复测通过后才算完成
- 发现“只处理部分文本/分段过少/视频全黑”等现象，优先修根因，不做表面兜底当作修复
- 任何日志不得输出密钥、Cookie、带签名参数的完整 URL
- 未经明确要求不做 git commit、不做发布、不做上传

## 常用环境变量
- SELF_MEDIA_LOG_LEVEL: DEBUG/INFO/WARNING/ERROR
- SELF_MEDIA_ENABLE_UPLOAD: 1 开启上传，0 关闭上传（用于安全回归测试）
- SELF_MEDIA_VIDEO_MIN_DURATION_RATIO: step3_video 最小时长比例（默认 0.3）
