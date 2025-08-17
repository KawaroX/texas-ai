# syntax=docker/dockerfile:1.7

# FastAPI + WebSocket
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.11-slim

# ---- 基础依赖（最小化 + 清理 apt 缓存）----
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- 依赖镜像与超时（可被 --build-arg 覆盖）----
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TIMEOUT=120
ENV PIP_INDEX_URL=$PIP_INDEX_URL \
    PIP_TIMEOUT=$PIP_TIMEOUT \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ---- 仅拷贝 requirements 以最大化缓存命中 ----
COPY ./requirements.txt /app/requirements.txt

# ---- 使用 BuildKit 缓存 pip（重复构建不再重复下载）----
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -U pip && \
    pip install --prefer-binary -r requirements.txt

# 代码一般由 docker-compose 的 volume 覆盖；如需内置，也可：
# COPY . /app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]