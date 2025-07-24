# Qdrant 向量数据库集成说明

## 启动 Qdrant 服务

在项目根目录下执行以下命令启动 Qdrant 服务：

```bash
docker-compose up -d qdrant
```

或者，如果你想启动所有服务（包括 Qdrant）：

```bash
docker-compose up -d
```

## 验证 Qdrant 是否就绪

启动后，可以通过以下命令检查 Qdrant 是否正常运行：

```bash
curl http://localhost:6333/health
```

如果服务正常，你应该会收到类似以下的响应：
```json
{
  "title": "qdrant - vector search engine",
  "status": "200 OK",
  "version": "1.x.x"
}
```

## 访问 Web UI（可选）

如果需要可视化管理 Qdrant，可以在浏览器中打开：
http://localhost:6334

## 在项目中使用 Qdrant

Qdrant 现在可以通过以下地址在你的应用中访问：
- HTTP API: http://qdrant:6333 (在 Docker 网络内部)
- HTTP API: http://localhost:6333 (从宿主机)

## 服务配置详情

Qdrant 服务配置如下：
- 镜像: qdrant/qdrant:latest
- 容器名: qdrant
- 端口映射:
  - 6333: Qdrant HTTP/gRPC 接口
  - 6334: Qdrant Web UI
- 数据持久化: 使用 Docker volume `qdrant_storage`
- 重启策略: unless-stopped
- 网络: 连接到现有的 `texas-net` 网络

## 数据持久化

Qdrant 的数据将持久化存储在 Docker volume `qdrant_storage` 中，即使容器被删除，数据也不会丢失。
