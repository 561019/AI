# 文档表格解析引擎接口说明 v1.0

## 定位与边界

服务代码为 `l2.document_table_parse`，能力编号为 `CAP.DOCUMENT.PARSE`。它只接收流程执行引擎通过 L2 对内通道派发的任务和文件 `artifact_ref`，输出结构化正文、表格、字段来源与异常信息；不做计算、汇总、单位换算或权限授予。

图片和PDF OCR直接调用硅基流动托管的`PaddlePaddle/PaddleOCR-VL-1.5`。API密钥由部署环境通过`SILICONFLOW_API_KEY`注入，不出现在任务信封、数据库或解析结果中。本地不部署OCR模型。

## 1. 派发接口

`POST /v1/platform/document-parse`

请求使用 `application/json`：

```json
{
  "protocol_version": "1.0",
  "message_id": "msg_001",
  "trace_id": "trace_001",
  "request_id": "req_001",
  "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
  "target": {"layer": "L2", "service_code": "l2.document_table_parse"},
  "channel": "l2_internal",
  "route_type": "task.dispatch",
  "action": "document.parse",
  "capability_id": "CAP.DOCUMENT.PARSE",
  "capability_dictionary_version": "2026.07.17",
  "registry_version": "registry_2026.07.17",
  "actor": {"person_id": "person_001", "tenant_id": "tenant_demo", "roles": ["employee"]},
  "context": {
    "workflow_instance_id": "flow_001",
    "node_id": "node_parse_001",
    "task_id": "task_parse_001",
    "artifact_refs": [{
      "ref_id": "artifact_invoice_001",
      "resource_type": "document",
      "source_system": "l1.data",
      "storage_key": "artifacts/project_001/invoice.jpg",
      "original_name": "invoice.jpg",
      "version": "1",
      "data_labels": ["project:demo"],
      "allowed_actions": ["read"]
    }]
  },
  "idempotency_key": "flow_001-node_parse_001-v1",
  "deadline_at": "2026-07-17T18:00:00+08:00",
  "confidence_threshold": 0.85
}
```

接口按 `idempotency_key` 去重，先按当前真人执行 `data.read` 和 `document:parse` 判权，再返回 `accepted`；不传递模型密钥、数据库凭据或文件正文。

## 2. 标准回复

所有回复包含 `protocol_version`、`message_id`、`trace_id`、`request_id`、`parent_message_id`、`source`、`target`、`task_id` 与 `status`。

| reply_type | HTTP | 含义 |
| --- | --- | --- |
| `accepted` | 202 | 任务已登记，`data.status_query` 给出查询地址。 |
| `success` | 200 | 解析完成，返回 `result_ref` 与人工复核标志。 |
| `failed` | 200 | 返回稳定错误码、说明和 `retryable`。 |

查询：`GET /v1/platform/document-parse/{job_id}`。

## 3. 硅基流动OCR接口

图片先统一转换为PNG；PDF由PyMuPDF渲染为PNG页面，然后逐页调用：

```json
{
  "model": "PaddlePaddle/PaddleOCR-VL-1.5",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,...", "detail": "high"}},
      {"type": "text", "text": "OCR:"}
    ]
  }],
  "max_tokens": 8192,
  "stream": false
}
```

请求地址为`https://api.siliconflow.cn/v1/chat/completions`，使用Bearer认证。响应正文取自：

```json
{"choices": [{"message": {"content": "识别正文或Markdown/HTML表格"}}]}
```

硅基流动响应不包含校准置信度和检测级坐标。解析结果明确使用配置置信度和整页归一化坐标；默认置信度`0.80`低于默认复核阈值`0.85`，因此进入人工复核。数字原样保留，解析服务不得自行修正或计算。

## 4. 存储与回调

当前服务保存原件对象与解析任务；正式接入时由流程执行/数据操作协调完成文件三拆：原件文件库、结构化目录、语义向量库。长期存档必须另发 `data.persist` 并经真人确认；解析成功不等于自动存档。

正式回调使用 `flow.callback`，至少包含原 `trace_id`、`workflow_instance_id`、`node_id`、`task_id`、结果引用、错误码及回调幂等键。当前项目先提供查询接口供联调，流程执行服务上线后再启用回调投递。
