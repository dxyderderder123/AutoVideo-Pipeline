# 全自动英语视频制作工作流

## 👤 工程序言：致王磊老师的个人自述

王磊老师您好：

我是邓星元，一名专注于 **AI 自动化工作流与物理交叉应用**的开发者（初试总分 374，高等数学 133 / 量子力学 127）。

本项目不仅是一个自动化视频生产工具，它更是我在备考期间，利用有限时间与硬件资源，探索 **“高通量数据清洗 -> 异构模型调度 -> 全链路自动化生产”** 系统能力的工程实践。

### 为什么这个项目对我的学术生涯具有意义？

1. **工程落地能力 (Engineering Maturity)**：在尝试 `Remotion+Manim` 等高层抽象框架由于渲染效率与稳定性瓶颈失败后，我通过底层的 **Python + FFmpeg** 原生堆栈实现了 100% 的生产闭环。这证明了我不仅能紧跟前沿工具（Playwright/LLM Agent），更能针对实际工业负载进行务实的架构优化。
2. **数据流转思维 (Data Pipeline Mindset)**：从运营哲学科普账号（[哲明星](https://www.douyin.com/user/MS4wLjABAAAAsZfpRN0z5dC2QUfxlFhoODEsP1nOLAGiSV_KDFXLgRqRJy6ClYPNv8SK9yXUzhlt?from_tab_name=main) 5.5 万关注）的 0 到 1 搭建中，我积累了处理大规模非结构化数据、API 熔断保护与多线程并发调度的实战经验。这种对“自动化流水线”的深刻理解，是我快速适配 **AI for Science (AI4S)** 研究节奏的核心竞争力。
3. **学术志向与跨界适配**：本科期间我对物理基础理论（量子力学、热统、数理方程均 95+）与数值计算（ Cantor 分形衍射、黑洞相变建模）有扎实的掌握。我极度渴望能将这种工程实现能力引入您的课题组，从自媒体应用开发转向**量子多体物理与人工智能交叉领域**的深耕。

---

## ⚙️ 项目架构与工作流程

这个项目实现了从**输入文章到视频成品**的全链路自动化逻辑，自媒体账号为 [英韵星](https://space.bilibili.com/1740211863?spm_id_from=333.1387.follow.user_card.click)。系统具备 [硬件感知（GPU锁）](src_english/utils_hardware.py)、[API熔断降级](src_english/utils_rate_limiter.py) 和 [多线程并行能力](src_english/workflow.py)，确保了生产环境的稳健性。

### 1. 核心自动化管线 (Pipeline)

系统将视频制作逻辑拆解为以下核心步骤，各模块分工明确：

| 阶段              | 对应文件                                          | 功能描述 (真实逻辑)                                  | 核心技术                  |
| :---------------- | :------------------------------------------------ | :--------------------------------------------------- | :------------------------ |
| **01&nbsp;分析** | [step1_analyze.py](src_english/step1_analyze.py)     | 将长文按语义切分为 20-30s 段落，提取视频搜索词       | LLM 语义分析              |
| **02&nbsp;配音** | [step2_tts.py](src_english/step2_tts.py)             | 生成配音音频（含 GPU 显存锁，防止多任务爆显存）      | **VibeVoice** 推理  |
| **03&nbsp;素材** | [step3_video.py](src_english/step3_video.py)         | 自动抓取视频素材。若 API 超限，则降级使用本地历史库  | Pexels/Pixabay API        |
| **04&nbsp;字幕** | [step5_subtitle.py](src_english/step5_subtitle.py)   | 优先调用 WhisperX 对齐，若环境缺失则改用词数比例计算 | WhisperX / 比例算法       |
| **05&nbsp;翻译** | [step6_translate.py](src_english/step6_translate.py) | 直译文稿并渲染为中英双语 ASS 字幕（含 \N 强制折行）  | LLM 翻译 + libass         |
| **06&nbsp;混剪** | [step7_merge.py](src_english/step7_merge.py)         | 执行复杂的 FFmpeg 滤镜链，完成音画同步与视频压制     | **FFmpeg** 底层滤镜 |
| **07&nbsp;封面** | [step8_cover.py](src_english/step8_cover.py)         | 基于文稿关键词自动生成横/竖版 AI 封面图              | SiliconCloud (KOLORS)     |
| **08&nbsp;发布** | [step9_upload.py](src_english/step9_upload.py)       | 自动登录并发布至B站，避开常见的 WAF 阻断             | bilibili-api 协议         |

### 2. 批量生产能力

该项目支持**一键扫描式批量生产**：

- **自动化入口**：系统自动扫描 [workspace/input/](workspace/input/) 目录下的所有 Markdown 文稿。
- **并行调度**：由 [scripts/batch_run.py](scripts/batch_run.py) 统筹。它会根据硬件负载（如 8GB 显存建议开启 1 个任务）动态调度并行任务数，在保证硬件安全的前提下最大化生产效率。
- **一键运行**：通过 [run_batch.bat](scripts/run_batch.bat) 即可启动完整的流水线任务。

---

## 📈 开发动机与技术历程

这个项目的产出不是一次简单的代码编写，也并不是我的最终目的。而是我在过去一年中，在平衡考研备考、探索经济独立以及追求物理与 AI 交叉研究过程中的一个阶段性记录。

### 1. 缘起：备考压力下的自动化探索

在准备物理考研初试期间，由于希望在不依赖家庭经济支持的前提下高效复习，我开始尝试通过 AI 自动化流程运营科普自媒体（哲学科普账号 [哲明星](https://www.douyin.com/user/MS4wLjABAAAAsZfpRN0z5dC2QUfxlFhoODEsP1nOLAGiSV_KDFXLgRqRJy6ClYPNv8SK9yXUzhlt?from_tab_name=main)，现关注量 5.5 万）。

* **初期瓶颈**：一年前，受限于 AI 对精确数学/几何关系的生成能力，我将方向从物理科普转向更具意象表达空间的哲学科普。
* **半自动化阶段**：当时采用 [ComfyUI](https://www.comfy.org/zh-cn/)（flux生图）+ [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)（ai声音克隆）的架构。流程涉及“原文提取 ->手动发给 Gemini 生成文稿和脚本 -> Python 素材生成 -> 人声降噪/混响处理，字幕修正 -> PR 辅助剪辑”。
* **存证**：此阶段的原始脚本和素材处理文件，已归档至项目根目录的 [archive/old_workflow/](archive/old_workflow/) 文件夹中。

### 2. 共鸣：从“应用探索”向“AI for Science”的转向

在备考过程中，我关注到王磊老师您在“物理与人工智能交叉领域”的研究方向，这让我意识到过去一两年的 AI 编程探索（AI Coding）不应仅仅停留在应用层的自媒体工具，而应转向更为严谨的学术研究（如 AI 驱动的物理模拟与自动化验证）。这成为我报考物理所、深耕 AI4S 方向的核心动力。

### 3. 攻坚：关于 Remotion 与 Manim 全自动化的试错

初试结束后，我曾计划利用一个月时间通过 [Playwright](https://github.com/microsoft/playwright)（自动化控制）+ [Remotion](https://www.remotion.dev/)（前端视频框架）+ [Manim](https://github.com/ManimCommunity/manim)（数学动画引擎）构建一套具备理科展现力的智能 Agent，并希望一次为敲门砖在出初试成绩前就联系您。

* **进展**：成功实现了基于 Playwright 的文稿与脚本一键生成自动化。
* **挫败**：但在渲染阶段遇到了巨大瓶颈——Remotion 产出的视频在全量自动化下视觉质量不稳（类似动态 PPT），而 Manim 在自动化脚本驱动下的几何逻辑表现极度不稳定。
* **反思**：这段失败的经历让我深刻理解到高层框架在工业级自动化一致性上的局限，但也锻炼了我对异构工具链（Playwright/Manim）的深度调试能力。

### 4. 现状：务实选择下的工程衍生品

在临近复试、全力投入《普通物理》与《四大力学》等专业知识复习的有限时间内，我果断止损，决定从之前的复杂失败中提取出最稳健的技术组件，利用 **Python + FFmpeg** 原生重构了目前这套全自动的英语视频工作流。

* **价值**：它证明了作者能够在资源限制（硬件负载、API 成本）与时间压力（专业课复试准备）下，迅速交付高质量工程方案的执行力。

---

## 🚀 后续研究与技术展望

这个项目是我在自动化视听工程领域的一个探索起始点。基于过去两年的持续观察与实操沉淀，我对 AI 驱动的“生产与教育”领域已有初步的系统性理解：

### 1. 全自动视频后期

目前的自动化管线（如本项目）正在将创作者从繁重的“后期重复劳动”中逐步解放，使其角色从“剪辑师”回归为“内容设计师”与“智识编排者”，从而把重心放回内容质量上。

* **行业先锋**：目前该方向已有显著的工业化实践，如 [林亦LYi](https://space.bilibili.com/4401694)、[数字游牧人](https://space.bilibili.com/4848323)、[空山猎人](https://space.bilibili.com/3493108557809994)、[数字黑魔法](https://space.bilibili.com/1235535223)、[我是阿众](https://space.bilibili.com/281120100)、[大圆镜科普](https://space.bilibili.com/1208823126)、[差评前沿部](https://space.bilibili.com/3546877542795556) 等博主。
* **核心趋势**：AI 原生工作流将大幅压缩优质内容的产出周期。

### 2. 教育大脑（AI4Education）：精密可视化与感性认知的融合

真正的 AI 教育不应只是文本问答，而应是“理性（Manim 几何动画）”与“感性（Remotion 沉浸式 UI）”的精密缝合：

* **技术愿景**：利用 [Manim](https://github.com/ManimCommunity/manim) 的科学动画支撑理科逻辑的底层演示，结合 [Remotion](https://www.remotion.dev/) 搭建动态响应式的前端视觉。
* **前沿动态**：融资千万美元的初创公司 [videotutor.io](https://videotutor.io/zh) ，以及开源学术项目 [manim-skills](https://github.com/xiaotianfotos/skills/tree/main/tutor) 已经展示了这种融合的巨大潜力。
* **产业趋势**：虽然字节跳动的 [豆包爱学](https://www.doubao.com/)、腾讯元宝的 [全学科解题大师](https://yuanbao.tencent.com/)、阿里通义千问的 [小讲堂](https://tongyi.aliyun.com/) 目前体验极差，但已经在探索视频化、互动化的讲解功能。因此如何高一致性地自动化生成此类内容是当前行业的核心研究命题。

### 3. 下一代交互（Next-Gen UX）：从单模态文本到流式动态音画

人类天然对动态音画有更强的处理带宽 and 情感共鸣。未来的 LLM 交互将跳出“对话框”的束缚，转向基于前端实时生成的流式（Streaming）交互。

* **终极逻辑**：利用 AI 实时将结构化指令转化为动态交互课件，以真正喜闻乐见的形式降低知识的“认知负载”。
