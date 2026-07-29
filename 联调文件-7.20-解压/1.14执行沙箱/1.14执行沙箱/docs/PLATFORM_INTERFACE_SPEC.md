# 执行沙箱平台调用接口 v1

## 1. 接口定位

本接口用于业务引擎层经基础模块层接口调用执行沙箱能力。业务应用层不得直接调用。

当前服务地址：

```text
http://10.60.66.97:8765
```

当前登记服务：

```text
execution_sandbox.run_task
```

## 2. 服务目录

```http
GET /api/v1/layer-interface/service-catalog
```

返回服务编号、调用路径、允许的业务引擎、请求字段、响应字段、场景目录和当前执行器。

## 3. 调用请求头

```http
Authorization: Bearer <platform-token>
X-Caller-Layer: business_engine
X-Engine-Id: flow-execution-engine
X-Company-Id: hanhe-group
X-Trace-Id: trace-20260715-0001
Content-Type: application/json
```

规则：

- `X-Caller-Layer` 只允许 `business_engine`。
- `X-Engine-Id` 必须是服务目录中的登记引擎。
- `X-Trace-Id` 必须与请求体 `trace_id` 一致。
- `X-Company-Id` 必须与 `caller.company_id` 一致；任务查询也必须处于同一公司范围。
- 相同追踪编号的相同请求不会重复执行。
- 相同追踪编号携带不同内容时返回 `409 trace_id_conflict`。

当前演示 token 配置在 `config.example.json`。生产环境应通过 `SANDBOX_PLATFORM_API_TOKEN` 环境变量注入并定期轮换。

## 4. 提交任务

```http
POST /api/v1/layer-interface/requests
```

请求示例：

```json
{
  "protocol_version": "1.0",
  "trace_id": "trace-20260715-0001",
  "service_code": "execution_sandbox.run_task",
  "reply_mode": "receipt",
  "caller": {
    "layer": "business_engine",
    "engine_id": "flow-execution-engine",
    "company_id": "hanhe-group",
    "user_id": "sales-user"
  },
  "payload": {
    "scenario_id": "s19_over_stock_warning",
    "agent": "supply-chain-agent",
    "limits": {
      "timeout_seconds": 10,
      "memory_mb": 512,
      "cpu_cores": 1
    },
    "input": {}
  }
}
```

说明：

- `reply_mode=receipt`：先返回受理回执，适合平台正式调用。
- `reply_mode=immediate`：等待任务结束后直接返回结果，适合短任务和联调测试。
- `caller.user_id` 当前由 mock 账号网关解析；未知用户默认拒绝。
- 权限列表不能由调用方自行提交，防止调用方伪造权限。

## 5. 受理回执

异步请求返回 HTTP `202`：

```json
{
  "protocol_version": "1.0",
  "trace_id": "trace-20260715-0001",
  "request_id": "req-1234567890abcdef",
  "service_code": "execution_sandbox.run_task",
  "reply_type": "acceptance_receipt",
  "status": "accepted",
  "progress": {"stage": "accepted", "percent": 0},
  "links": {
    "self": "/api/v1/layer-interface/requests/req-1234567890abcdef",
    "events": "/api/v1/layer-interface/requests/req-1234567890abcdef/events"
  }
}
```

`request_id` 是本模块受理编号，`trace_id` 是贯穿完整平台调用链的追踪编号，两者用途不同。

## 6. 查询状态和结果

```http
GET /api/v1/layer-interface/requests/{request_id}
```

进行中状态：

```text
accepted
running
```

终态：

```text
succeeded
rejected
failed
timeout
```

成功结果包含：

```json
{
  "reply_type": "result",
  "status": "succeeded",
  "output": {
    "task_id": "真实沙箱任务编号",
    "status": "success",
    "business_result": {},
    "result_files": [],
    "duration_ms": 542
  },
  "evidence": {
    "executor": "DockerTemplateExecutor",
    "runtime": {},
    "limits": {},
    "logs": [],
    "platform_checks": {}
  }
}
```

## 7. 查询进度事件

```http
GET /api/v1/layer-interface/requests/{request_id}/events
```

可观察事件包括：

```text
request.accepted
request.started
task.accepted
identity.resolved
permission.checked
sandbox.preparing
sandbox.result_collected
task.finished
request.finished / request.rejected / request.failed
```

## 8. 权限拒绝

权限不足时，返回标准拒绝：

```json
{
  "reply_type": "rejection",
  "status": "rejected",
  "reason": {
    "code": "permission_denied",
    "missing_permissions": ["invoice:read", "receipt:read"],
    "sandbox_started": false
  }
}
```

该状态表示请求格式合法，但真人没有执行当前场景的权限。Docker 不启动，资源成本为 0。

## 9. 接口级拒绝编码

| 编码 | HTTP | 含义 |
| --- | ---: | --- |
| `invalid_platform_token` | 401 | 服务调用凭证无效 |
| `caller_layer_not_allowed` | 403 | 业务应用层等非业务引擎层越层调用 |
| `engine_not_registered` | 403 | 调用引擎不在准入名单 |
| `identity_not_resolved` | 403 | 真人身份无法解析 |
| `caller_header_mismatch` | 400 | 请求头与请求体调用身份不一致 |
| `trace_id_mismatch` | 400 | 请求头与请求体追踪编号不一致 |
| `trace_id_conflict` | 409 | 同一追踪编号对应不同请求内容 |
| `service_not_registered` | 404 | 服务编号未登记 |
| `scenario_not_registered` | 404 | 场景编号未登记 |
| `invalid_limit` | 400 | CPU、内存或时长超出允许范围 |

## 10. curl 调用示例

```bash
TOKEN='hanhe-basic-layer-demo-token-change-before-production'
TRACE_ID='trace-20260715-0001'

curl -X POST 'http://10.60.66.97:8765/api/v1/layer-interface/requests' \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'X-Caller-Layer: business_engine' \
  -H 'X-Engine-Id: flow-execution-engine' \
  -H 'X-Company-Id: hanhe-group' \
  -H "X-Trace-Id: ${TRACE_ID}" \
  -H 'Content-Type: application/json' \
  -d '{
    "protocol_version":"1.0",
    "trace_id":"trace-20260715-0001",
    "service_code":"execution_sandbox.run_task",
    "reply_mode":"receipt",
    "caller":{
      "layer":"business_engine",
      "engine_id":"flow-execution-engine",
      "company_id":"hanhe-group",
      "user_id":"sales-user"
    },
    "payload":{
      "scenario_id":"s19_over_stock_warning",
      "agent":"supply-chain-agent",
      "limits":{"timeout_seconds":10,"memory_mb":512,"cpu_cores":1},
      "input":{}
    }
  }'
```
