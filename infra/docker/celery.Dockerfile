# celery.Dockerfile: 构建 Celery Worker 服务容器
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.11-slim

# 安装依赖
RUN apt-get update && apt-get install -y build-essential

WORKDIR /app

COPY ./requirements.txt /app/requirements.txt

# 安装 Python 依赖
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -U pip && \
    pip install --prefer-binary -r requirements.txt

CMD ["celery", "-A", "celery_app", "worker", "--loglevel=info"]
