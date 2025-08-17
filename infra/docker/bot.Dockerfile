# bot.Dockerfile: 构建 FastAPI + WebSocket 服务容器
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.11-slim

# 安装依赖
RUN apt-get update && apt-get install -y build-essential

# 设置工作目录
WORKDIR /app

# 拷贝项目依赖文件
COPY ./requirements.txt /app/requirements.txt

# 安装 Python 依赖
RUN pip install --upgrade pip && pip install -r requirements.txt

# 拷贝项目代码（由 docker-compose 的 volume 挂载为主）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]