#!/bin/bash

# Texas AI 管理面板 HTTP Basic Auth 部署脚本
# 用途：一键在服务器上部署 HTTP Basic Auth 认证
# 运行方式：ssh root@115.190.143.80 'bash -s' < scripts/deploy_admin_auth.sh

set -e  # 遇到错误立即退出

echo "======================================"
echo "Texas AI 管理面板认证部署脚本"
echo "======================================"
echo ""

# 进入项目目录
cd /root/texas-ai

# 步骤 1: 拉取最新代码
echo "[1/6] 拉取最新代码..."
gg git pull origin main || git pull origin main
echo "✅ 代码更新完成"
echo ""

# 步骤 2: 安装 htpasswd 工具
echo "[2/6] 检查 htpasswd 工具..."
if ! command -v htpasswd &> /dev/null; then
    echo "未找到 htpasswd，正在安装..."
    apt-get update && apt-get install -y apache2-utils
    echo "✅ htpasswd 安装完成"
else
    echo "✅ htpasswd 已安装"
fi
echo ""

# 步骤 3: 生成密码文件
echo "[3/6] 配置 HTTP Basic Auth 密码..."
echo "请设置管理面板访问密码（用户名: admin）"
echo "密码建议：至少16位，包含大小写字母、数字、特殊字符"
echo ""

# 检查密码文件是否已存在
if [ -f /root/texas-ai/nginx/.htpasswd ]; then
    echo "⚠️  密码文件已存在"
    read -p "是否要重新设置密码？(y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        htpasswd -c /root/texas-ai/nginx/.htpasswd admin
        echo "✅ 密码已更新"
    else
        echo "⏭️  跳过密码设置，使用现有密码"
    fi
else
    mkdir -p /root/texas-ai/nginx
    htpasswd -c /root/texas-ai/nginx/.htpasswd admin
    echo "✅ 密码文件创建成功"
fi
echo ""

# 步骤 4: 创建 nginx 配置文件
echo "[4/6] 部署 nginx 配置文件..."
if [ -f /root/texas-ai/nginx/conf.d/default.conf.template ]; then
    cp /root/texas-ai/nginx/conf.d/default.conf.template /root/texas-ai/nginx/conf.d/default.conf
    echo "✅ nginx 配置文件已创建"
else
    echo "❌ 错误：找不到 nginx 配置模板文件"
    echo "请确保已从 git 仓库拉取最新代码"
    exit 1
fi
echo ""

# 步骤 5: 检查 docker-compose.nginx.yml 配置
echo "[5/6] 检查 docker-compose 配置..."
if grep -q "/etc/nginx/.htpasswd" docker-compose.nginx.yml; then
    echo "✅ docker-compose.nginx.yml 已配置密码文件挂载"
else
    echo "⚠️  警告：docker-compose.nginx.yml 未配置密码文件挂载"
    echo "请手动在 nginx 服务的 volumes 部分添加："
    echo "  - ./nginx/.htpasswd:/etc/nginx/.htpasswd:ro"
    echo ""
    read -p "按 Enter 继续部署，或 Ctrl+C 取消..."
fi
echo ""

# 步骤 6: 重启服务
echo "[6/6] 重启服务..."
docker compose -f docker-compose.yml -f docker-compose.nginx.yml down
echo "正在启动服务（快速模式，不重新构建）..."
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d
echo "✅ 服务重启完成"
echo ""

# 验证部署
echo "======================================"
echo "部署完成！"
echo "======================================"
echo ""
echo "📊 服务状态："
docker compose -f docker-compose.yml -f docker-compose.nginx.yml ps
echo ""
echo "🔍 验证步骤："
echo "1. 访问: http://115.190.143.80/admin"
echo "2. 应该弹出用户名/密码对话框"
echo "3. 输入用户名: admin"
echo "4. 输入密码: [你刚才设置的密码]"
echo "5. 认证成功后显示管理面板"
echo "6. 右上角应显示: 🔒 已通过HTTP Basic Auth认证"
echo ""
echo "🔧 故障排查："
echo "查看 nginx 日志: docker compose -f docker-compose.yml -f docker-compose.nginx.yml logs nginx"
echo "查看 bot 日志: docker compose -f docker-compose.yml -f docker-compose.nginx.yml logs bot"
echo ""
echo "📚 详细文档："
echo "docs/ADMIN_AUTH_SETUP.md"
echo ""
