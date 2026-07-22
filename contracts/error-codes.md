# 平台错误码 v0.1

| 错误码 | HTTP | 可重试 | 含义 |
|---|---:|---:|---|
| `INVALID_REQUEST` | 400 | 否 | 请求格式或必填字段错误 |
| `UNSUPPORTED_PROTOCOL_VERSION` | 400 | 否 | 协议版本不支持 |
| `SOURCE_LAYER_FORBIDDEN` | 403 | 否 | 调用来源层不在准入名单 |
| `ACTOR_UNAUTHENTICATED` | 401 | 否 | 当前真人身份未认证 |
| `PERMISSION_DENIED` | 403 | 否 | 当前真人无权执行动作 |
| `CAPABILITY_NOT_FOUND` | 404 | 否 | 能力未登记 |
| `CAPABILITY_DISABLED` | 503 | 是 | 能力已停用 |
| `RESOURCE_NOT_FOUND` | 404 | 否 | 文件、数据、资产或任务不存在 |
| `RESOURCE_VERSION_CONFLICT` | 409 | 否 | 引用版本不一致 |
| `IDEMPOTENCY_CONFLICT` | 409 | 否 | 同一幂等键对应了不同请求内容 |
| `PRECONDITION_REQUIRED` | 422 | 否 | 缺少规则、数据、授权或其他前置条件 |
| `CONFIRMATION_REQUIRED` | 202 | 否 | 流程已挂起，等待真人确认 |
| `CONFIRMATION_STALE` | 409 | 否 | 确认对象已变化或已处理 |
| `RISK_BLOCKED` | 422 | 否 | 驾驭或安全规则阻止执行 |
| `CONTENT_POLICY_VIOLATION` | 422 | 否 | 输入或输出触发合规红线 |
| `DEPENDENCY_UNAVAILABLE` | 503 | 是 | 下游模块暂不可用 |
| `MODEL_RATE_LIMITED` | 429 | 是 | 模型服务限流 |
| `MODEL_OUTPUT_INVALID` | 502 | 是 | 模型输出不符合结构约束 |
| `DEADLINE_EXCEEDED` | 504 | 视动作而定 | 请求超过截止时间 |
| `CALLBACK_DELIVERY_FAILED` | 502 | 是 | 回调投递失败 |
| `INTERNAL_ERROR` | 500 | 是 | 未分类内部异常 |

错误对象必须包含 `code`、`message`、`retryable`；可附加 `details`，但不得泄露堆栈、密钥或内部数据库信息。
