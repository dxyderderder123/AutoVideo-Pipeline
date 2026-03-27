# Git 回溯（最小必需版）

Git = “时光机”。把你项目在某个稳定状态时做一个“快照”（commit），以后任何时候都能回到那个快照。

## 0) 你现在的项目状态
- 已初始化仓库：`.git/` 已存在
- 已有 `.gitignore`：默认忽略 `.env`、`workspace/`、`logs/`、`venv/` 等（避免把密钥和产物提交进去）

## 1) 日常使用（推荐你只记这 4 条）
### 1.1 看看改了什么
```bash
git status
```

### 1.2 选择要存档的文件（快照内容）
```bash
git add .
```

### 1.3 做一次快照（commit）
```bash
git commit -m "snapshot: pipeline stable"
```

### 1.4 查看历史
```bash
git log --oneline --decorate --graph -n 20
```

## 2) 回到某个稳定版本（两种常用方式）
### 2.1 只“回滚代码”，不改历史（更安全）
适合你想撤销最近一次/几次改动，但不想把历史搞乱：
```bash
git revert <commit_id>
```
它会生成一个“反向提交”，把那次改动撤回来。

### 2.2 直接回到某个 commit（会改变工作区）
适合你实验失败、想立刻回到某个提交的状态：
```bash
git restore --source <commit_id> -- .
```
然后你可以选择再 commit 一次，把“回到稳定状态”的结果也存档。

## 3) 最实用的小技巧
### 3.1 做一个“里程碑标签”
```bash
git tag v1-stable
```
以后回到这个里程碑：
```bash
git restore --source v1-stable -- .
```

### 3.2 临时存放当前改动（不想提交但又要切换）
```bash
git stash -u
```
恢复：
```bash
git stash pop
```

## 4) 重要安全提醒
- 不要提交 `.env`（已经被 `.gitignore` 忽略）
- 日志/产物目录也不要提交（已经忽略）
