# Texas AI 项目优化回退指南

> **重要提示**: 此文档包含回退到优化前状态的详细步骤，请妥善保管，不要提交到版本库！

## 📊 优化前系统状态信息

**记录时间**: 2025-09-04 14:17:00

### Git 状态
- **当前分支**: `main`
- **最新提交**: `e17c155a5d6f592907250e1621abe211d1803a03`
- **提交信息**: `feat(image_generation): 优化多角色场景图和工作日服装提示词`
- **工作树状态**: 干净 (无未提交更改)
- **远程同步状态**: 与origin/main同步

### 备份分支
- **备份分支**: `remotes/origin/backup/origin-main-2025-08-14-163220`

## 🚨 紧急回退步骤

### 方法一: 基于Commit Hash回退 (推荐)

如果优化后代码出现问题，执行以下命令：

```bash
# 1. 停止所有运行中的服务
docker compose down

# 2. 回退到优化前的commit
git reset --hard e17c155a5d6f592907250e1621abe211d1803a03

# 3. 如果有已推送的错误提交，强制推送回退 (谨慎使用)
# git push origin main --force

# 4. 重新启动服务
docker compose up --build -d
```

### 方法二: 使用备份分支回退

```bash
# 1. 停止服务
docker compose down

# 2. 切换到备份分支
git checkout remotes/origin/backup/origin-main-2025-08-14-163220

# 3. 创建新的本地分支
git checkout -b rollback-branch

# 4. 合并到main分支
git checkout main
git reset --hard rollback-branch

# 5. 重新启动服务
docker compose up --build -d
```

### 方法三: 逐步回退 (精细控制)

```bash
# 1. 查看优化前后的差异
git log --oneline

# 2. 选择性回退特定文件
git checkout e17c155a5d6f592907250e1621abe211d1803a03 -- path/to/file.py

# 3. 提交回退的更改
git add -A
git commit -m "rollback: 回退优化更改"
```

## 📋 回退验证清单

优化回退后，请逐一检查：

### ✅ 服务状态检查
```bash
# 检查容器状态
docker compose ps

# 检查服务日志
docker compose logs -f bot
docker compose logs -f worker

# 检查API健康状态
curl http://localhost:8000/llm-config/gemini?k=k8yyjSAVsbavobY92oTGcN7brVLUAD
```

### ✅ 功能验证
- [ ] FastAPI服务启动正常 (http://localhost:8000)
- [ ] Mattermost连接正常
- [ ] Celery任务执行正常
- [ ] Redis缓存工作正常
- [ ] PostgreSQL数据库连接正常
- [ ] 图片生成功能正常
- [ ] AI对话功能正常

### ✅ 数据完整性检查
```bash
# 检查数据库连接
docker compose exec db psql -U texas_user -d texas_db -c "\dt"

# 检查Redis数据
docker compose exec redis redis-cli ping

# 检查关键配置文件
ls -la .env
cat requirements.txt | head -10
```

## 🔧 常见回退问题处理

### 问题1: 容器启动失败
```bash
# 清理容器和镜像
docker compose down -v
docker system prune -a -f

# 重新构建
docker compose up --build -d
```

### 问题2: 数据库连接问题
```bash
# 检查数据库容器
docker compose logs db

# 重启数据库服务
docker compose restart db
```

### 问题3: 依赖版本冲突
```bash
# 强制重新安装依赖
docker compose build --no-cache bot
docker compose build --no-cache worker
```

## 📝 优化前关键文件备份

### 重要配置文件
- `.env` - 环境配置
- `requirements.txt` - Python依赖
- `docker-compose.yml` - 容器配置
- `CLAUDE.md` - 项目文档

### 核心代码文件
- `services/ai_service.py` (1474行) - 主要AI服务
- `app/mattermost_client.py` (1107行) - WebSocket客户端
- `core/chat_engine.py` - 聊天引擎
- `core/context_merger.py` - 上下文合并器

## 🚀 重新开始优化

如需重新进行优化，建议：

1. **创建特性分支**:
   ```bash
   git checkout -b optimization-v2
   ```

2. **小步迭代**: 一次只优化一个模块

3. **充分测试**: 每次更改后运行完整测试

4. **备份重要数据**: 优化前备份数据库和配置

## 📞 紧急联系

如遇到无法解决的问题：
1. 立即停止所有服务: `docker compose down`
2. 保留错误日志和系统状态
3. 按本文档步骤进行回退
4. 记录具体错误信息用于后续排查

---
**文档创建时间**: 2025-09-04 14:17:00  
**系统状态**: 稳定运行  
**备份状态**: 已确认