#!/bin/bash

# 主动交互系统测试运行脚本
# 在宿主机上运行，通过Docker执行测试

echo "🚀 开始运行主动交互系统测试..."
echo "================================================"

# 检查docker-compose是否可用
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose 未安装或不在PATH中"
    exit 1
fi

# 检查docker-compose.yml是否存在
if [ ! -f "docker-compose.yml" ]; then
    echo "❌ 未找到docker-compose.yml文件，请在项目根目录运行此脚本"
    exit 1
fi

# 检查服务是否运行
echo "🔍 检查Docker服务状态..."
if ! docker-compose ps | grep -q "Up"; then
    echo "⚠️  Docker服务未运行，尝试启动..."
    docker-compose up -d
    echo "⏳ 等待服务启动..."
    sleep 10
fi

# 显示当前运行的服务
echo "📋 当前运行的服务:"
docker-compose ps

# 运行测试脚本
echo ""
echo "🧪 开始执行主动交互测试..."
echo "================================================"

# 假设你的主要应用服务名为 'app' 或 'texas-ai'
# 请根据你的docker-compose.yml中的服务名进行调整
SERVICE_NAME="bot"

# 检查服务是否存在
if ! docker-compose ps | grep -q "$SERVICE_NAME"; then
    echo "❌ 服务 '$SERVICE_NAME' 未找到，请检查docker-compose.yml中的服务名"
    echo "可用的服务:"
    docker-compose ps --services
    exit 1
fi

# 执行测试
docker-compose exec $SERVICE_NAME python /app/scripts/test_active_interaction.py

# 检查执行结果
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 测试执行完成"
else
    echo ""
    echo "❌ 测试执行失败"
    exit 1
fi

echo ""
echo "📊 如需查看详细日志，可以运行:"
echo "   docker-compose logs $SERVICE_NAME"
echo ""
echo "🔧 如需进入容器调试，可以运行:"
echo "   docker-compose exec $SERVICE_NAME bash"
echo ""
echo "🧹 如需清理测试数据，可以运行:"
echo "   docker-compose exec $SERVICE_NAME python -c \"import redis; r=redis.Redis.from_url('redis://redis:6379'); r.flushdb()\""
