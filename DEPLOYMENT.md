# 部署操作指南

本文档记录了Texas AI项目的GitHub上传和服务器部署操作流程。

## 提交代码到GitHub

### 1. 检查状态
```bash
git status
git diff
git log --oneline -5
```

### 2. 添加并提交
```bash
git add <修改的文件>
git commit -m "$(cat <<'EOF'
<类型>(<范围>): <简短描述>

- <详细变更内容1>
- <详细变更内容2>
- <详细变更内容3>

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### 3. 推送到远程
```bash
git push origin main
```

## 服务器部署

### 服务器信息
- **SSH地址**: `ssh root@115.190.143.80`
- **项目路径**: `/root/texas-ai`

### 🔑 关键概念：何时需要 `--build`

由于项目使用 **volume 挂载**（`.:/app`），代码文件会实时同步到容器内，因此：

#### ✅ **不需要 `--build` 的情况**（90%的场景）
- 只修改了 Python 代码（`.py` 文件）
- 修改了配置文件（`.env`、YAML配置等）
- 修改了文档（`.md` 文件）
- 修改了脚本（`.sh` 文件）

👉 **快速部署命令**（推荐）：重启容器即可，代码自动生效

#### ❌ **需要 `--build` 的情况**（少数场景）
- 修改了 `Dockerfile`（如 `infra/docker/bot.Dockerfile`）
- 修改了 `requirements.txt`（Python依赖变更）
- 修改了 `docker-compose.yml` 中的构建配置
- 首次部署或长时间未构建

👉 **完整构建命令**：需要重新构建镜像

---

### 部署步骤

#### 1. 拉取最新代码
```bash
ssh root@115.190.143.80 "cd /root/texas-ai && git pull origin main"
```

**注意**: 如果服务器上git速度较慢，可以使用 `gg` 前缀加速：
```bash
ssh root@115.190.143.80 "cd /root/texas-ai && gg git pull origin main"
```
⚠️ `gg` 前缀仅在服务器上有效，本地环境不支持。

#### 2. 重启服务

服务器有两个docker-compose配置文件：
- `docker-compose.yml` - 主要服务配置
- `docker-compose.nginx.yml` - Nginx代理配置

**方式A：快速部署**（无需构建，推荐用于代码修改）
```bash
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml down && docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d"
```

**方式B：完整构建**（用于依赖或Dockerfile变更）
```bash
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml down && docker compose -f docker-compose.yml -f docker-compose.nginx.yml up --build -d"
```

#### 3. 检查服务状态
```bash
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml ps"
```

## 重要注意事项

1. **使用 `docker compose`** 而不是 `docker-compose`（注意没有连字符）
2. **两个配置文件** 都需要同时使用，因为服务器需要启动Nginx
3. **服务依赖** 确保PostgreSQL、Redis、Qdrant等服务都正常启动
4. **重启顺序** 先down再up --build确保使用最新代码
5. **提交格式** 遵循项目的提交消息格式规范

## 常用命令快速参考

### 完整部署流程（一键操作）

#### 场景1️⃣：代码修改（最常用，推荐）
```bash
# 本地提交
git add .
git commit -m "feat: 更新内容描述"
git push origin main

# 服务器快速部署（不需要构建）
ssh root@115.190.143.80 "cd /root/texas-ai && gg git pull origin main && docker compose -f docker-compose.yml -f docker-compose.nginx.yml down && docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d"
```

#### 场景2️⃣：依赖或配置变更（需要构建）
```bash
# 本地提交
git add .
git commit -m "build: 更新依赖或Dockerfile"
git push origin main

# 服务器完整构建部署
ssh root@115.190.143.80 "cd /root/texas-ai && gg git pull origin main && docker compose -f docker-compose.yml -f docker-compose.nginx.yml down && docker compose -f docker-compose.yml -f docker-compose.nginx.yml up --build -d"
```

💡 **提示**：如果不确定，使用场景1（快速部署）即可，因为volume挂载会自动同步代码

## Git工作流优化策略

### 问题：小修改产生无意义commit
为避免格式化、小调整等修改占据独立commit，可使用以下策略：

### 策略1：Amend Commit（推荐）
适用于刚提交完，需要小幅修改的情况：
```bash
# 小修改后
git add .
git commit --amend --no-edit  # 追加到上一个commit
git push --force-with-lease origin main  # 安全强推

# 服务器快速部署（代码修改通常不需要 --build）
ssh root@115.190.143.80 "cd /root/texas-ai && gg git pull origin main && docker compose -f docker-compose.yml -f docker-compose.nginx.yml down && docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d"
```

### 策略2：临时分支
适用于需要临时测试功能的情况：
```bash
# 创建临时分支
git checkout -b temp-fixes
git add .
git commit -m "临时修改测试"
git push origin temp-fixes

# 服务器部署临时分支（快速部署）
ssh root@115.190.143.80 "cd /root/texas-ai && gg git pull origin temp-fixes && docker compose -f docker-compose.yml -f docker-compose.nginx.yml down && docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d"

# 确认无误后合并到main
git checkout main
git merge temp-fixes
git push origin main
git branch -d temp-fixes
git push origin --delete temp-fixes
```

### 策略3：Stash临时保存
适用于暂时不想提交但需要拉取的情况：
```bash
# 保存当前修改
git stash push -m "临时修改"

# 拉取最新代码
git pull origin main

# 需要时恢复修改
git stash pop
```

### 查看服务日志
```bash
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml logs -f <service-name>"
```

### 进入容器调试
```bash
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml exec <service-name> /bin/bash"
```

## 故障排查

### 代码修改后没生效？
**原因**：容器未重启，或服务进程缓存了旧代码

**解决方案**：
```bash
# 重启服务
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml restart bot worker"
```

### 依赖安装失败？
**原因**：修改了 `requirements.txt` 但未重新构建镜像

**解决方案**：
```bash
# 使用 --build 参数重新构建
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml up --build -d"
```

### 服务无法启动？
**诊断步骤**：
```bash
# 1. 查看服务状态
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml ps"

# 2. 查看具体服务日志
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml logs --tail=50 bot"

# 3. 检查依赖服务健康状态
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml ps | grep healthy"
```

### 快速重启单个服务
```bash
# 只重启 bot 服务
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml restart bot"

# 只重启 worker 服务
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml restart worker"
```

## 部署决策流程图

```
修改了什么？
│
├─ Python代码 (.py)           → 快速部署 (无 --build)
├─ 配置文件 (.env, .yml)      → 快速部署 (无 --build)
├─ 文档/脚本 (.md, .sh)       → 快速部署 (无 --build)
│
├─ requirements.txt           → 完整构建 (加 --build)
├─ Dockerfile                 → 完整构建 (加 --build)
└─ docker-compose.yml 构建项  → 完整构建 (加 --build)
```