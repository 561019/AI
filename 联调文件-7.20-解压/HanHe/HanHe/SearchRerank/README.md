# SearchRerank

该工程承接 `ChunkingVectorization` 写入 Milvus 的 `hanhe_document_chunks` collection，完成两阶段检索：

1. 使用硅基流动 `Qwen/Qwen3-Embedding-8B` 将查询编码为 1024 维向量。
2. 在 Milvus 中以 COSINE 相似度召回候选 chunk。
3. 按文档范围、业务标签和人工复核状态过滤候选。
4. 调用硅基流动 `Qwen/Qwen3-Reranker-8B` 重排序。
5. 返回 chunk 文本、两种分数、页码、block 来源及 `Documentparsing` 资源地址。

重排序不会生成新的 chunk，也不会覆盖 Milvus。最终结果是每次查询的即时 JSON 响应；Milvus 中仍保存向量化后的 chunk 主数据。

## 安装与配置

在现有 Conda `hanhe` 环境中安装：

```bash
cd /media/cbl123/data3/WYQ/HanHe/SearchRerank
python -m pip install -e ".[api]"
cp .env.example .env
```

编辑 `.env`，至少填写 `SILICONFLOW_API_KEY`。其余默认值已经与当前两个上游工程一致：

```dotenv
MILVUS_URI=http://localhost:19530
MILVUS_COLLECTION=hanhe_document_chunks
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
EMBEDDING_DIMENSIONS=1024
RERANK_MODEL=Qwen/Qwen3-Reranker-8B
```

先验证配置、Milvus 连接和 collection 维度：

```bash
search-rerank --env-file .env check
```

## 测试当前 PDF

当前 PDF 的 chunk 带有 `needs_review=true`，因此技术验证时要显式加入 `--include-review-required`：

```bash
search-rerank --env-file .env search "这个文档主要讲了什么？" \
  --document-id 651e157af37441b686ecaf2b23337112 \
  --business-tag project:pdf-test \
  --include-review-required \
  --candidate-k 20 \
  --top-n 3
```

正常业务默认不加 `--include-review-required`，低质量、待人工确认的解析片段不会进入结果。

## HTTP API

启动服务，建议使用 `8001`，避免与 `Documentparsing` 的 `8000` 冲突：

```bash
python -m uvicorn search_rerank.api:app --env-file .env --host 0.0.0.0 --port 8001
```

查询：

```bash
curl -sS -X POST http://localhost:8001/v1/search \
  -H 'Content-Type: application/json' \
  -H 'X-Actor-ID: demo-user' \
  -d '{
    "query": "这个文档主要讲了什么？",
    "candidate_k": 20,
    "top_n": 3,
    "document_ids": ["651e157af37441b686ecaf2b23337112"],
    "business_tags": ["project:pdf-test"],
    "include_review_required": true
  }' | python -m json.tool
```

命中项中的 `references.original`、`references.result` 和 `references.blocks` 是相对于 `Documentparsing` 服务的路径。生产环境应配置 `PERMISSION_API_URL`；未配置时只允许本地测试身份 `demo-user`。

## 测试

```bash
python -m unittest discover -s tests -v
```

硅基流动重排序请求格式参考[官方 Rerank API](https://docs.siliconflow.cn/cn/api-reference/rerank/create-rerank)。
