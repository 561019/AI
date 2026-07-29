# Docker Build Resource Optimization

更新时间：2026-07-13

## 目标

降低 backend 镜像构建期间的内存、网络和磁盘占用，同时完整保留 BGE、Sentence Transformers、Milvus、API 和现有 Compose profiles 功能。

## 调整内容

1. 新增 `backend/requirements-runtime.txt`，并由 `pyproject.toml` 动态读取，避免维护两份依赖清单。
2. Dockerfile 先安装运行依赖，再复制 `app`、`scripts` 和 Alembic 文件。
3. 应用本体使用 `pip install --no-deps .`，代码变化不再重新安装 Torch 和语义依赖。
4. Torch 显式从 `https://download.pytorch.org/whl/cpu` 安装 CPU 版本，不再包含 CUDA 运行库。
5. 新增 `backend/.dockerignore`，排除字节码、本地虚拟环境、测试缓存和模型缓存。
6. 保留 `PIP_NO_CACHE_DIR=1` 和所有原运行配置。

## 验证结果

```text
镜像 Size:          3,011,718,003 -> 469,162,037 bytes  (-84%)
依赖安装层:         5.58 GB -> 1.57 GB                 (-72%)
Torch:              2.13.0+cpu
torch.version.cuda:  None
首次构建:           约 225 秒
相同内容重复构建:   约 9 秒，所有构建层 CACHED
backend运行内存:    约 86 MiB
Postgres运行内存:   约 55 MiB
```

分两轮清理旧 Build Cache，共释放约 19.4 GB 磁盘空间；当前 Build Cache 约 2.34 GB，保留刚生成的 CPU 依赖缓存用于后续快速构建。

## 构建方式

默认构建命令不变：

```powershell
docker compose build backend
docker compose up -d --no-build backend
```

如未来需要使用其他 Torch 仓库，可覆盖构建参数：

```powershell
docker build --build-arg PYTORCH_INDEX_URL=<index-url> -t intent-analysis-engine-backend backend
```

## 功能回归

```text
backend测试: 343 passed, 4 skipped
复杂对话评测: 100/100
在线API: DATA_ANALYSIS_PROBLEM / ENG_ANALYTICS_FORECASTING
sentence-transformers: 5.6.0
pymilvus: 3.0.0
```
