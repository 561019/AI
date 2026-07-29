# Docker Development Profiles

本文件说明开发环境的 Docker Compose profile 使用方式。生产部署配置不在此处定义。

## 默认开发栈

默认只启动后端和数据库：

```powershell
docker compose up -d
```

默认服务：

- `backend`
- `postgres`

用途：

- Level1 规则匹配
- Task Builder
- Input Validator
- TaskList API
- 不依赖 Milvus / MinIO / etcd

## 语义检索栈

需要验证 Level2 Semantic Matcher、Milvus collection 或向量初始化时启用：

```powershell
docker compose --profile semantic up -d
```

额外启动：

- `etcd`
- `minio`
- `milvus`

默认的 `backend` 和 `postgres` 仍会启动。

## 前端可视化平台

需要浏览器演示时启用：

```powershell
docker compose --profile frontend up -d
```

额外启动：

- `frontend`

入口：

```text
http://127.0.0.1:5173/
```

## LLM Demo 服务

需要 Level3 本地 demo 模型服务时启用：

```powershell
docker compose --profile llm up -d
```

额外启动：

- `local-model-service`

## 常用组合

前端演示但不启用语义栈：

```powershell
docker compose --profile frontend up -d
```

前端 + 语义栈：

```powershell
docker compose --profile frontend --profile semantic up -d
```

完整开发栈：

```powershell
docker compose --profile frontend --profile semantic --profile llm up -d
```

## 注意

- 开发默认 healthcheck 使用 `/health`，避免未启用 Milvus 时 backend 被标记为 unhealthy。
- 需要验证 Milvus 连通性时，使用 `/health/ready` 或启动 `semantic` profile。
- 汇报前不要执行 `docker compose up -d --build`，避免重新构建 BGE 依赖栈导致内存占用过高。
