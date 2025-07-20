# celery.Dockerfile: 构建 Celery Worker 服务容器
FROM python:3.11-slim

# 安装依赖
RUN apt-get update && apt-get install -y build-essential

WORKDIR /app

COPY ./requirements.txt /app/requirements.txt

RUN pip install --upgrade pip && pip install -r requirements.txt

CMD ["celery", "-A", "celery_app", "worker", "--loglevel=info"]
