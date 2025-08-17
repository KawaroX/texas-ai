# syntax=docker/dockerfile:1.7

# Celery Worker
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TIMEOUT=120
ENV PIP_INDEX_URL=$PIP_INDEX_URL \
    PIP_TIMEOUT=$PIP_TIMEOUT \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY ./requirements.txt /app/requirements.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -U pip && \
    pip install --prefer-binary -r requirements.txt

# COPY . /app

CMD ["celery", "-A", "celery_app", "worker", "--loglevel=info"]