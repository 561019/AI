# 平台接口契约 v0.1

本目录是平台接口优先开发的第一版契约。它定义公共协议与“意图分析 → 真人确认 → 流程执行 → 权限判定 → 规则计算 → 结果返回”的最小闭环，不包含业务实现。

## 强制边界

- 所有前后端、层间、层内和模块间交互必须通过接口完成。
- 禁止跨层调用、直接读取其他模块数据库、共享内部对象或导入其他模块代码完成协作。
- 业务应用层只能调用业务引擎层；业务引擎层只能调用基础模块层。
- 同层协作必须经过该层接口。基础模块层接口判权时允许机制性直达权限判定服务。
- 所有请求必须携带 `message_id`、`request_id`、`trace_id`、`source`、`target`、`actor` 与 `idempotency_key`。
- 模块不得信任客户端自行声明的身份；`actor` 必须由账号网关验证并由层接口签入。

## 文件索引

- `platform-api-conventions.md`：传输、状态、版本、权限与重试规则。
- `common-envelope.openapi.yaml`：公共请求、回复、引用和错误模型。
- `error-codes.md`：平台错误码表。
- `async-task-and-callback.md`：异步任务、回调与通知协议。
- `layer-gateways.openapi.yaml`：业务应用层、业务引擎层、基础模块层统一入口。
- `capability-registry.openapi.yaml`：能力登记与解析接口。
- `identity-permission.openapi.yaml`：身份上下文与权限判定接口。
- `model-gateway.openapi.yaml`：统一大模型接口。
- `file-data-reference.openapi.yaml`：文件、数据引用和受控读取接口。
- `intent-analysis.openapi.yaml`：意图分析与意图确认接口。
- `workflow-execution.openapi.yaml`：流程启动、挂起、恢复与回调接口。
- `rule-calculation.openapi.yaml`：规则计算接口。
- `module-interface-template.md`：后续模块接口定义模板。
- `contract-review-v0.1.md`：四项核心协议的审核结论与冻结门槛。
- `end-to-end-examples.md`：最小闭环的异步、确认、拒绝和计算示例。
- `module-adapter-matrix-v0.1.md`：四个现有模块到平台标准字段的逐项适配矩阵。

## 当前状态

版本为 `0.1.0-draft`。字段冻结前允许调整；冻结为 `1.0.0` 后只允许向后兼容扩展，破坏性变更必须升级主版本。
