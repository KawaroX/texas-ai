#!/bin/bash

cd "$(dirname "$0")/.."

echo "🚀 启动 Texas AI 本地开发环境..."

# 自动初始化 .env 文件
if [ ! -f .env ]; then
  echo "📂 未找到 .env，正在复制模板..."
  cp .env.template .env
fi

# 启动服务
docker compose up --build -d

echo "✅ 启动完成！服务运行状态如下："
docker compose ps

echo ""
echo "📡 FastAPI 地址: http://localhost:8000"
echo "🧠 PostgreSQL: 本地端口 5432"
echo "🧾 Redis: 本地端口 6379"