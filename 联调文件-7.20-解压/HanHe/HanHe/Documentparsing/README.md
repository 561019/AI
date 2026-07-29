# 文档表格解析引擎——核心联调包

本交付包用于验证平台整体框架的任务派发、文件读取、文档解析、标准化文档生成和结果回传逻辑。包内不包含前端、工作汇报、真实密钥、本地模型、虚拟环境和数据库数据。

## 模块边界

输入为原始文件或artifact_ref；输出为存放在MinIO/S3中的`standard-document/v1`标准文档包，并在PostgreSQL登记任务和包信息。本模块不负责后续Chunk分块。

## 目录

```text
src/doc_table_engine/        后端源码
tests/                       自动化测试
examples/                    小型联调样例
templates/                   字段模板样例
deploy/integration/          无前端联调Docker配置
docs/                        接口、标准文档包规范和联调准备表
.env.example                 无真实密钥的环境变量示例
requirements-api.txt         Python依赖
pyproject.toml               Python项目定义
```

## 启动

需要先安装Docker Desktop。图片、扫描件和PDF直接调用硅基流动托管的
`PaddlePaddle/PaddleOCR-VL-1.5`，本地不安装模型，也不需要GPU。

```powershell
Copy-Item .env.example .env
```

在`.env`中填写`SILICONFLOW_API_KEY`，然后启动服务：

```powershell
$env:COMPOSE_BAKE = "false"
docker compose -p doc-table-engine-integration `
  -f .\deploy\integration\docker-compose.integration.yml `
  up --build
```

接口文档：`http://localhost:8000/docs`

健康检查：

```powershell
Invoke-RestMethod http://localhost:8000/health
```

## 核心接口

- `POST /v1/platform/document-parse`：平台标准任务派发。
- `GET /v1/platform/document-parse/{job_id}`：查询任务和标准文档包引用。
- `GET /v1/jobs/{job_id}/standard-document/manifest.json`：读取Manifest。
- `GET /v1/jobs/{job_id}/standard-document/blocks.jsonl`：读取后续分块主输入。
- `GET /v1/jobs/{job_id}/standard-document.zip`：下载完整标准文档包。

## 自动化测试

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -v
```

当前核心包测试覆盖直接解析、权限、异步任务、人工复核、幂等派发、Markdown/JSON清洗、标准文档包生成，以及硅基流动OCR请求、PDF逐页渲染和表格映射。

## 远程OCR说明

- 图片统一转换为PNG后，以base64图像调用硅基流动`/v1/chat/completions`。
- PDF由PyMuPDF在服务内渲染为页面图片，再逐页调用远程模型；本地只做渲染，不运行OCR模型。
- 硅基流动响应不提供校准置信度和检测级坐标。当前使用整页`0,0,1000,1000`坐标和可配置的保守置信度，默认`0.80`，因此在默认`0.85`阈值下进入人工复核。
- HTML或Markdown表格会转换为结构化表格；模型只返回纯文本时保存为页面正文块。
- 请求按页面计费和限流，最大页数、渲染DPI、图片像素、超时及重试均可通过`.env`配置。
- PDF页面和图片会以base64发送给硅基流动。生产使用前必须确认文档数据分级、第三方处理授权、地域和留存策略满足组织要求。

## 正式联调替换项

- `SILICONFLOW_API_KEY`通过部署环境的密钥管理系统注入。
- `PERMISSION_API_URL`替换为权限中心。
- PostgreSQL和MinIO配置替换为平台数据层配置。
- 与流程执行引擎确认artifact_ref、flow.callback和幂等协议。
