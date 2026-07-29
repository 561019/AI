# 标准文档分块与向量化引擎

本工程消费 `Documentparsing` 生成的 `standard-document/v1` 标准包，保存可审计的分块过程文件，调用硅基流动 `Qwen/Qwen3-Embedding-8B` 生成文本向量，并使用确定性 `chunk_id` 幂等写入 Milvus。

## 输入与边界

输入可以是展开后的标准包目录，也可以是从文档解析接口下载的 ZIP：

```text
standard-documents/{job_id}/v1/
  manifest.json
  blocks.jsonl
  layout.json
  assets/tables/*.json
  ...
```

分块以 `blocks.jsonl` 为主输入，使用 `layout.json.reading_order` 恢复顺序。`document.md` 只用于展示，不作为分块源；表格块必须读取其 `asset_ref`，不能只向量化表格名称。

## 分块策略

- 正文：短段落合并，超长段落优先按句子边界拆分，默认目标 600、上限 800、重叠 80 个估算 Token。
- PDF/图片：同页文本可以合并，不跨页合并。
- PPT：不跨幻灯片合并。
- Word/Markdown：按 `heading_path` 和原子段落合并，标题路径变化时立即切块。
- 字段：模板字段独立成块，并带字段名。
- 表格：读取 `assets/tables/*.json`，按行切分，每个块重复表头并保留行号范围。
- 人工复核：所有块都写入过程文件；`needs_review=true` 默认不向量化。设置 `EMBED_REVIEW_REQUIRED=true` 才允许入库。

计数器是稳定的中英文混合估算器，不需要在线下载 Qwen tokenizer。默认块上限远低于 Qwen3-Embedding-8B 的 32K 上下文，因此不会依赖服务端截断。

## 分块过程文件

输出目录为：

```text
process-output/chunk-documents/{document_id}/v{package_version}/
  manifest.json
  normalized-blocks.jsonl
  chunks.jsonl
  trace.jsonl
  vectorization-manifest.json
  vectorization.jsonl
```

- `manifest.json`：源包哈希、策略参数、统计和过程文件校验和。
- `normalized-blocks.jsonl`：按最终阅读顺序保存的输入块快照。
- `chunks.jsonl`：完整 Chunk，包括正文、来源块、页码、坐标、表格行范围和权限标签。
- `trace.jsonl`：记录每个 Chunk 是语义合并还是表格行切分。
- `vectorization.jsonl`：记录模型、维度、Milvus 集合和写入状态，不重复保存大体积向量。

## 安装

需要 Python 3.11 或更高版本：

```bash
cd ChunkingVectorization
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
```

在 `.env` 中填写 `SILICONFLOW_API_KEY`。真实密钥不能提交到仓库。

## 启动 Milvus

推荐使用 Milvus 官方 standalone 配置。以当前 2.6 系列为例：

```bash
mkdir -p deploy
curl -L https://github.com/milvus-io/milvus/releases/download/v2.6.20/milvus-standalone-docker-compose.yml \
  -o deploy/milvus-standalone.yml
docker compose -f deploy/milvus-standalone.yml up -d
```

默认连接地址为 `http://localhost:19530`。生产环境通过 `MILVUS_URI`、`MILVUS_TOKEN` 和 `MILVUS_DATABASE` 接入 Milvus 集群或 Zilliz Cloud。

## 使用

只分块，不调用外部服务：

```bash
chunk-vector chunk /path/to/standard-document/v1
chunk-vector chunk /path/to/standard-document.zip --output-dir process-output
```

对已有过程包向量化并写入 Milvus：

```bash
chunk-vector index process-output/chunk-documents/{document_id}/v1
```

一次完成分块、向量化和入库：

```bash
chunk-vector ingest /path/to/standard-document.zip
```

检索验证：

```bash
chunk-vector search "合同的付款条件是什么？" --top-k 5
chunk-vector search "销售额最高的区域" --document-id {document_id}
```

也可以直接下载 `Documentparsing` 生成的标准包：

```bash
curl -H "X-Actor-ID: demo-user" \
  http://localhost:8000/v1/jobs/{job_id}/standard-document.zip \
  -o standard-document.zip
chunk-vector ingest standard-document.zip
```

## 向量和 Milvus Schema

默认请求参数：

```json
{
  "model": "Qwen/Qwen3-Embedding-8B",
  "dimensions": 1024,
  "encoding_format": "float"
}
```

该模型原生输出 4096 维。硅基流动支持 Matryoshka 降维，本项目默认 1024 维以降低约 75% 的向量存储与计算成本；需要最大维度时将 `EMBEDDING_DIMENSIONS` 改为 `4096`，并使用新的 Milvus 集合。已有集合的向量维度不能原地修改。

Milvus 集合包含：

- `chunk_id`：SHA-256 字符串主键；相同源包、策略和文本生成相同 ID。
- `embedding`：`FLOAT_VECTOR`，`AUTOINDEX`，`COSINE`。
- `document_id`、包版本、块序号、块类型和正文。
- `needs_review`、源文件哈希和策略版本。
- `metadata`：页码、坐标、来源块、表格资源、业务标签和置信度。

写入使用 `upsert`，因此重复执行不会创建相同主键的重复记录。

## 配置

关键环境变量见 `.env.example`：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `EMBEDDING_MODEL` | `Qwen/Qwen3-Embedding-8B` | 硅基流动模型名称 |
| `EMBEDDING_DIMENSIONS` | `1024` | 向量维度 |
| `EMBEDDING_BATCH_SIZE` | `16` | 单次 API 文本数量 |
| `MILVUS_COLLECTION` | `document_chunks` | Milvus 集合 |
| `CHUNK_TARGET_TOKENS` | `600` | 期望块大小 |
| `CHUNK_MAX_TOKENS` | `800` | 块硬上限 |
| `CHUNK_OVERLAP_TOKENS` | `80` | 长文本内部重叠 |
| `EMBED_REVIEW_REQUIRED` | `false` | 是否向量化待复核内容 |

## 测试

离线测试不调用硅基流动和 Milvus：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

覆盖固定版面分页、待复核隔离、表格行切分、ZIP 安全读取、过程文件，以及使用测试替身完成向量化入库。

## 外部接口依据

- [硅基流动 Embeddings API](https://api-docs.siliconflow.cn/docs/api/embeddings-post)
- [Qwen3 Embedding 官方仓库](https://github.com/QwenLM/Qwen3-Embedding)
- [Milvus 创建 Collection](https://milvus.io/docs/create-collection.md)
- [Milvus Upsert](https://milvus.io/api-reference/pymilvus/v3.0.x/MilvusClient/Vector/upsert.md)

