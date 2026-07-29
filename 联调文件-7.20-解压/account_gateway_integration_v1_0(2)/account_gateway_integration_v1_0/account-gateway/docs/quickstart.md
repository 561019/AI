# 快速启动

本指南用于在本地启动 `account-gateway` 并验证健康检查接口。

## 环境要求

- Go 1.22+
- Docker 与 Docker Compose
- Python 3.11+
- Python 环境中安装 pytest

## 安装

从仓库根目录执行：

```sh
cd account-gateway
go mod download
python -m pip install pytest pytest-timeout requests
```

如果你的 shell 需要 Compose v2 语法，手动命令可以使用 `docker compose`。本仓库的测试 fixture 与脚本面向本地 Docker Compose 环境。

## 运行

运行一键测试流程：

```sh
make test
```

手动本地启动时，运行：

```sh
docker-compose up
```

如果本地流程没有自动启动网关，在另一个 shell 中运行：

```sh
make run
```

## 验证

检查健康接口：

```sh
curl http://localhost:8080/health
```

预期结果：HTTP 200，并返回网关的健康响应体。

执行前确认 make 目标：

```sh
make -n test
```

输出中应包含 `pytest tests/e2e`。
