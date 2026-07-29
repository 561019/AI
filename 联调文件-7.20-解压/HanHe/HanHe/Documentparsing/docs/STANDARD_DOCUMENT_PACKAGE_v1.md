# 标准解析文档包 v1

文档表格解析引擎负责把原始文件解析、清洗并保存为可供知识库后续分块的标准文档包。本模块不生成 Chunk。

## 对象存储结构

每个任务写入 MinIO/S3 前缀：

```text
standard-documents/{job_id}/v1/
  manifest.json
  document.md
  blocks.jsonl
  layout.json
  source/reference.json
  pages/page-0001.webp
  assets/images/img-0001.png
  assets/images/img-0001.json
  assets/tables/table-0001.json
  assets/tables/table-0001.parquet
```

`manifest.json`、`document.md`、`blocks.jsonl`、`layout.json` 和 `source/reference.json` 必须生成。页面、图片和表格目录按源文件实际内容生成。

## 文件职责

- `document.md`：清洗后的统一可读正文，保留块锚点与表格资源链接。
- `blocks.jsonl`：后续分块模块的主输入，一行一个有稳定 `block_id` 的语义块。
- `layout.json`：阅读顺序、页码和 0～1000 归一化坐标；流式文档没有物理坐标时进入 `logical_blocks`。
- `manifest.json`：包版本、源文件哈希、解析 Profile、解析器/模型、状态、统计、资源清单和警告。
- `assets/tables/*.json`：规范表格单元格、行列、值类型、置信度和来源。
- `assets/tables/*.parquet`：矩形表格的分析副本。
- `pages/*.webp`：图片/GIF/TIFF 等可直接渲染文件的页面预览。
- `assets/images/*`：从 DOCX、PPTX、XLSX/XLSM 容器中提取的媒体资源。

## Profile

| Profile | 来源 |
| --- | --- |
| `fixed-layout` | PDF、PNG、JPG、GIF、BMP、TIFF、WebP |
| `flow-document` | DOCX、Markdown |
| `slide-document` | PPTX |
| `tabular-document` | XLS/XLSX/XLSM、CSV/TSV |
| `structured-data` | JSON |

## PostgreSQL登记

`document_packages` 表登记 `job_id`、文档包版本、Profile、状态、原件哈希、对象前缀、Manifest键和完整元数据。任务结果的 `standard_document` 字段同时返回以下入口：

```json
{
  "schema": "standard-document/v1",
  "document_id": "...",
  "package_version": 1,
  "profile": "fixed-layout",
  "object_prefix": "standard-documents/{job_id}/v1",
  "manifest_key": "standard-documents/{job_id}/v1/manifest.json",
  "document_key": "standard-documents/{job_id}/v1/document.md",
  "blocks_key": "standard-documents/{job_id}/v1/blocks.jsonl",
  "layout_key": "standard-documents/{job_id}/v1/layout.json"
}
```

## 读取接口

```http
GET /v1/jobs/{job_id}/standard-document/manifest.json
GET /v1/jobs/{job_id}/standard-document/document.md
GET /v1/jobs/{job_id}/standard-document/blocks.jsonl
GET /v1/jobs/{job_id}/standard-document/layout.json
GET /v1/jobs/{job_id}/standard-document/assets/tables/table-0001.json
```

请求必须携带 `X-Actor-ID`，并通过 `artifact.read` 权限校验。生产环境中的分块模块也可以根据对象键通过数据层读取，不需要取得 MinIO/S3密钥。

## 当前限制

- PDF和PPTX页面预览需要独立文档渲染器；未配置时 Manifest 会记录警告，但正文、块、布局和表格仍正常生成。
- DOCX/PPTX/Excel内嵌图片可以提取，图片与正文块的精确锚定关系需要后续版解析器增强。
- 人工复核改变任务状态时不重写历史解析包；需要发布修订版时应生成新的 `package_version`。
