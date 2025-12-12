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
```bash
# 本地提交
git add .
git commit -m "feat: 更新内容描述"
git push origin main

# 服务器部署（普通速度）
ssh root@115.190.143.80 "cd /root/texas-ai && git pull origin main && docker compose -f docker-compose.yml -f docker-compose.nginx.yml down && docker compose -f docker-compose.yml -f docker-compose.nginx.yml up --build -d"

# 服务器部署（加速版本，如果git较慢）
ssh root@115.190.143.80 "cd /root/texas-ai && gg git pull origin main && docker compose -f docker-compose.yml -f docker-compose.nginx.yml down && docker compose -f docker-compose.yml -f docker-compose.nginx.yml up --build -d"
```

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

# 服务器部署
ssh root@115.190.143.80 "cd /root/texas-ai && gg git pull origin main && docker compose -f docker-compose.yml -f docker-compose.nginx.yml down && docker compose -f docker-compose.yml -f docker-compose.nginx.yml up --build -d"
```

### 策略2：临时分支
适用于需要临时测试功能的情况：
```bash
# 创建临时分支
git checkout -b temp-fixes
git add .
git commit -m "临时修改测试"
git push origin temp-fixes

# 服务器部署临时分支
ssh root@115.190.143.80 "cd /root/texas-ai && gg git pull origin temp-fixes && docker compose -f docker-compose.yml -f docker-compose.nginx.yml down && docker compose -f docker-compose.yml -f docker-compose.nginx.yml up --build -d"

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