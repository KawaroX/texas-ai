# 管理面板 HTTP Basic Auth 认证设置指南

本文档说明如何为 `/admin` 管理面板添加 HTTP Basic Auth 认证。

## 📋 概览

**已完成的代码修改**（本地仓库）：
- ✅ 后端 `app/main.py`: `/admin` 端点自动注入 ADMIN_K 到 HTML
- ✅ 前端 `admin_dashboard.html`: 移除密钥输入框，自动使用注入的密钥

**需要在服务器上执行的操作**：
- 🔧 生成 HTTP Basic Auth 密码文件
- 🔧 修改 nginx 配置添加认证
- 🚀 重启服务应用更改

## 🔐 安全机制说明

### 双层认证架构

1. **第一层：HTTP Basic Auth（nginx层）**
   - 浏览器弹出用户名/密码对话框
   - 由 nginx 验证身份
   - 只有认证通过才能访问 `/admin` 页面

2. **第二层：API密钥验证（应用层）**
   - 服务器自动将 `ADMIN_K` 注入到 HTML 的 JavaScript 中
   - 前端自动使用注入的密钥调用管理API
   - 用户无需手动输入密钥

### 认证流程

```
用户访问 /admin
    ↓
Nginx 弹出认证对话框
    ↓
输入用户名/密码
    ↓
认证成功 → 返回 HTML（含注入的 ADMIN_K）
    ↓
前端自动使用 ADMIN_K 调用 API
    ↓
后端验证 ADMIN_K → 返回数据
```

## 🚀 服务器部署步骤

### 步骤 1: 提交并推送代码

在**本地**执行：

```bash
# 提交代码修改
git add app/main.py admin_dashboard.html docs/ADMIN_AUTH_SETUP.md
git commit -m "$(cat <<'EOF'
feat(admin): implement HTTP Basic Auth with auto API key injection

- 后端修改：
  * /admin 端点自动注入 ADMIN_K 到 HTML 的 window.INJECTED_API_KEY
  * 移除前端手动输入密钥的需求

- 前端修改：
  * 移除 API 密钥输入框
  * getApiKey() 函数改为使用注入的密钥
  * 移除 localStorage 密钥存储逻辑
  * 添加"已通过HTTP Basic Auth认证"状态提示

- 文档：
  * 添加 ADMIN_AUTH_SETUP.md 部署指南

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
EOF
)"

# 推送到远程仓库
git push origin main
```

### 步骤 2: 连接到服务器

```bash
ssh root@115.190.143.80
cd /root/texas-ai
```

### 步骤 3: 拉取最新代码

```bash
gg git pull origin main
```

### 步骤 4: 生成 HTTP Basic Auth 密码文件

**重要：请设置一个强密码！**

```bash
# 安装 htpasswd 工具（如果未安装）
apt-get update && apt-get install -y apache2-utils

# 创建密码文件（用户名: admin）
# 执行后会提示输入密码两次
htpasswd -c /root/texas-ai/nginx/.htpasswd admin
```

**示例输出**：
```
New password: [输入你的密码]
Re-type new password: [再次输入]
Adding password for user admin
```

**密码建议**：
- 至少 16 位
- 包含大小写字母、数字、特殊字符
- 不要使用常见密码

### 步骤 5: 创建 nginx 配置文件

在服务器上创建 nginx 配置文件：

```bash
cat > /root/texas-ai/nginx/conf.d/default.conf << 'EOF'
server {
    listen 80;
    server_name _;

    # 管理面板 - 需要 HTTP Basic Auth
    location /admin {
        auth_basic "Texas AI Admin Panel";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass http://texas-bot:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Debug API - 需要 HTTP Basic Auth
    location /debug/ {
        auth_basic "Texas AI Debug API";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass http://texas-bot:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Gallery API - 需要 HTTP Basic Auth
    location /gallery/ {
        auth_basic "Texas AI Gallery API";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass http://texas-bot:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 其他所有请求（Mattermost 等）
    location / {
        proxy_pass http://mattermost:8065;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 支持
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF
```

### 步骤 6: 修改 docker-compose.nginx.yml

确保密码文件被挂载到 nginx 容器中。

检查 `docker-compose.nginx.yml` 文件，确认 nginx 服务的 volumes 配置：

```bash
cat docker-compose.nginx.yml | grep -A 10 "volumes:"
```

**如果没有挂载密码文件**，需要编辑配置：

```bash
nano docker-compose.nginx.yml
```

在 nginx 服务的 volumes 部分添加：

```yaml
services:
  nginx:
    image: nginx:latest
    ports:
      - "80:80"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./nginx/.htpasswd:/etc/nginx/.htpasswd:ro  # 添加这一行
    depends_on:
      - bot
      - mattermost
```

保存后退出（Ctrl+O, Enter, Ctrl+X）。

### 步骤 7: 重启服务

**方式A：快速部署**（推荐，只重启代码）

```bash
docker compose -f docker-compose.yml -f docker-compose.nginx.yml down
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d
```

**方式B：完整重启**（如果方式A有问题）

```bash
docker compose -f docker-compose.yml -f docker-compose.nginx.yml down
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up --build -d
```

### 步骤 8: 验证部署

1. **检查服务状态**：
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.nginx.yml ps
   ```

   确认所有服务都是 `Up` 状态。

2. **检查 nginx 日志**：
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.nginx.yml logs nginx | tail -20
   ```

3. **访问管理面板**：

   在浏览器中访问：`http://115.190.143.80/admin`

   - ✅ 应该弹出用户名/密码对话框
   - ✅ 输入 `admin` 和你设置的密码
   - ✅ 认证成功后显示管理面板
   - ✅ 右上角显示 "🔒 已通过HTTP Basic Auth认证"
   - ✅ 无需手动输入 API 密钥，功能正常使用

## 🔧 故障排查

### 问题 1: 没有弹出认证对话框

**可能原因**：nginx 配置未生效

**解决方法**：
```bash
# 检查 nginx 配置文件是否存在
ls -la /root/texas-ai/nginx/conf.d/default.conf

# 检查密码文件是否存在
ls -la /root/texas-ai/nginx/.htpasswd

# 重启 nginx 服务
docker compose -f docker-compose.yml -f docker-compose.nginx.yml restart nginx

# 查看 nginx 日志
docker compose -f docker-compose.yml -f docker-compose.nginx.yml logs nginx
```

### 问题 2: 密码错误（401 Unauthorized）

**可能原因**：密码文件未正确挂载或密码错误

**解决方法**：
```bash
# 进入 nginx 容器检查
docker compose -f docker-compose.yml -f docker-compose.nginx.yml exec nginx cat /etc/nginx/.htpasswd

# 如果文件不存在，检查 docker-compose.nginx.yml 的 volumes 配置
# 重新生成密码文件
htpasswd -c /root/texas-ai/nginx/.htpasswd admin

# 重启服务
docker compose -f docker-compose.yml -f docker-compose.nginx.yml restart nginx
```

### 问题 3: API 调用失败（401 错误）

**可能原因**：ADMIN_K 未正确注入

**解决方法**：
```bash
# 查看应用日志
docker compose -f docker-compose.yml -f docker-compose.nginx.yml logs bot | tail -50

# 在浏览器控制台检查
# 打开浏览器开发者工具（F12）→ Console 标签
# 输入: window.INJECTED_API_KEY
# 应该显示密钥值（不是 undefined）
```

### 问题 4: 页面显示但功能异常

**解决方法**：
```bash
# 清除浏览器缓存
# Chrome/Edge: Ctrl+Shift+Delete → 清除缓存
# Firefox: Ctrl+Shift+Delete → 清除缓存

# 强制刷新页面
# Windows: Ctrl+F5
# Mac: Cmd+Shift+R
```

## 📊 安全检查清单

部署后，请确认以下安全措施：

- [ ] ✅ `/admin` 需要 HTTP Basic Auth 认证
- [ ] ✅ `/debug/` 需要 HTTP Basic Auth 认证
- [ ] ✅ `/gallery/` 需要 HTTP Basic Auth 认证
- [ ] ✅ 密码文件权限正确（600 或更严格）
- [ ] ✅ 使用强密码（至少16位，包含大小写字母、数字、特殊字符）
- [ ] ✅ ADMIN_K 在 .env 文件中设置为强随机字符串
- [ ] ✅ .env 文件不在 git 仓库中（已在 .gitignore）
- [ ] ✅ 浏览器开发者工具中看不到明文密码（只能看到注入的 ADMIN_K）

## 🔑 凭据管理

### 使用的凭据

1. **HTTP Basic Auth**（nginx 层）
   - 用户名: `admin`
   - 密码: [你设置的强密码]
   - 存储位置: `/root/texas-ai/nginx/.htpasswd`

2. **API 密钥**（应用层）
   - 变量名: `ADMIN_K`
   - 默认值: `k8yyjSAVsbavobY92oTGcN7brVLUAD`
   - 存储位置: `.env` 文件（或使用默认值）
   - 注入到: `window.INJECTED_API_KEY`

### 修改密码

**修改 HTTP Basic Auth 密码**：
```bash
ssh root@115.190.143.80
htpasswd /root/texas-ai/nginx/.htpasswd admin  # 会提示输入新密码
docker compose -f docker-compose.yml -f docker-compose.nginx.yml restart nginx
```

**修改 API 密钥**（不推荐频繁修改）：
```bash
ssh root@115.190.143.80
cd /root/texas-ai
nano .env  # 修改 ADMIN_K=新的随机字符串
docker compose -f docker-compose.yml -f docker-compose.nginx.yml restart bot
```

## 📚 相关文档

- `docs/ADMIN_PANEL_TODO.md` - 管理面板开发进度
- `docs/ADMIN_DASHBOARD_GUIDE.md` - 管理面板使用指南
- `DEPLOYMENT.md` - 通用部署流程
- `docker-compose.nginx.yml` - Nginx 容器配置

---

**部署完成后，请妥善保管你的密码！**
