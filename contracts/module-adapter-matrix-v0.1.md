# 四模块接口适配矩阵 v0.1

审计对象：2026-07-20 交付的意图分析、流程执行、规则计算和权限模块。结论以实际路由与数据模型代码为准，README/OpenAPI 作为辅助。

## 1. 总体结论

| 模块 | 当前正式入口 | 契约成熟度 | 第一轮闭环 | 正式平台结论 |
|---|---|---:|---|---|
| 意图分析 | `POST /api/v1/intent/analyze` | 中 | 适配器可接通 | 适配器 + 轻微修改 |
| 流程执行 | `POST /api/instruction` 仅见参考契约；交付包无完整 HTTP 服务入口 | 中低 | 需先包装服务 | 必须修改 |
| 规则计算 | `POST /api/v1/instructions` | 较高 | 适配器可接通 | 适配器 + 轻微修改 |
| 权限 | `POST /api/permission/check` | 较高 | 适配器可接通 | 适配器 + 极小修改 |

“第一轮闭环”允许保留交付包中的本地 mock；“正式平台”必须遵守所有交互均通过接口的约束，因此不能继续使用跨模块本地类调用或本地模拟适配器。

---

## 2. 意图分析引擎

### 2.1 实际接口

- 主入口：`POST /api/v1/intent/analyze`
- 补充澄清：`POST /api/v1/intent/clarification/answer`
- 历史查询：`GET /api/v1/intent/history`
- 健康检查：`GET /health`、`GET /health/ready`
- 另有旧入口：`POST /api/intent-analysis`，与主入口模型不一致。

### 2.2 请求映射

| 现有字段 | 平台标准字段 | 处理方式 | 说明 |
|---|---|---|---|
| `text` | `payload.utterance` | 重命名 | 直接映射 |
| `user_id` | `actor.actor_id` | 重命名 | 禁止使用现有默认值 `anonymous`；必须来自已验证身份 |
| `conversation_id` | `context.conversation_id` | 移位 | 平台侧必填 |
| `project_id` | `context.project_id` | 移位 | 可空 |
| `history[]` | `payload.history[]` 或上下文服务返回 | 结构转换 | 第一版可透传；正式版优先传上下文引用，避免重复大正文 |
| `debug` | 不进入正式业务契约 | 丢弃/运维开关 | 生产请求禁止由普通用户开启 |
| 无 | `trace_id/request_id/message_id` | 适配器补齐并透传 | 引擎内部记录也应保存 `trace_id` |
| 无 | `idempotency_key/deadline_at` | 适配器校验 | 当前引擎没有幂等和截止时间约束 |

### 2.3 输出映射

| 现有字段 | 平台标准字段 | 处理方式 | 说明 |
|---|---|---|---|
| `success=true` | `status=success` | 枚举转换 | 仅表示分析接口完成，不代表业务流程完成 |
| `success=false` | `status=failed` | 枚举转换 | `error.code/message/details` 可复用 |
| `data.tasks[].task_id` | `data.tasks[].task_id` | 直接映射 | 应保证全链路唯一 |
| `task_type` | `capability_code` | 查能力字典转换 | 不能直接把任务类型当能力编号 |
| `task_description` | `description` | 重命名 | 直接映射 |
| `dependencies` | `dependencies` | 直接映射 | 当前实现已经是任务编号数组 |
| `action/object/required_inputs` | `parameters` | 组合转换 | 保留原始结构供流程执行使用 |
| `missing_inputs` | `data.required_inputs` | 结构转换 | 缺失时流程进入 `waiting_human` 或 `waiting_dependency` |
| `clarification_required` | `data.clarification_required` | 直接映射 | 这是“信息澄清”，不是架构要求的最终意图确认 |
| `confidence` | `data.tasks[].confidence` | 直接映射 | 不用于自动越过真人确认 |

### 2.4 冲突与缺口

1. 现有接口不接受平台统一信封，也不验证来源层、服务身份、截止时间和幂等键。
2. `task_type` 不是正式 `capability_code`，必须经能力登记映射。
3. 当前“澄清”与“意图确认”不是同一机制；即使无需澄清，仍要由平台生成意图确认卡片。
4. 存在两套意图接口与两套数据模型，应明确 `/api/v1/intent/analyze` 为唯一保留主入口。
5. 模块内部 Model Gateway 仍属于本模块实现；正式平台必须改为调用统一大模型调度 API。
6. 上下文虽然已有外部 Provider Client，但正式路径必须通过基础模块层接口调用上下文服务。
7. `request_id` 等部分内部字段被 `exclude=True`，无法保证完整追踪回传。

### 2.5 改造结论

- 第一轮闭环：外置适配器即可接通。
- 正式平台：轻微修改。增加平台信封入口或只保留适配入口；将大模型与上下文依赖改为 HTTP 接口；保存并回传追踪字段；关闭普通用户调试开关。

---

## 3. 流程执行引擎

### 3.1 实际接口

交付包提供 `engine.py`、`platform_adapter.py` 和 OpenAPI 参考，但没有发现完整 FastAPI/HTTP 服务启动入口。参考 OpenAPI 包含：

- `POST /api/instruction`
- `POST /api/flow/start|get|list|decide|audit`
- `GET /api/registry`

平台适配器支持动作：`flow.start/get/list/cancel/callback`、`human.decide`、超时扫描和投递重试等。

### 3.2 统一信封映射

| 现有字段 | 平台标准字段 | 处理方式 | 说明 |
|---|---|---|---|
| `protocol_version` | 同名 | 直接映射 | 都使用 `1.0` |
| `message_id/request_id/trace_id` | 同名 | 直接映射 | 当前实现未强制 UUID |
| `parent_message_id` | `parent_request_id` | 语义不等价 | 消息父子关系与请求父子关系应分别保留 |
| `occurred_at` | 建议新增标准字段或放审计元数据 | 保留 | 当前公共信封缺少请求发生时间，建议后续补入 |
| `source.layer=L2/L4` | `source.layer=business_engine/business_application` | 枚举转换 | 禁止继续把 L4 当正式层名 |
| `source.service_code` | `source.module` | 重命名 | 同时保留服务编码 |
| `target.service_code` | `target.module/capability` | 查登记转换 | 目标地址不得写死 |
| `channel` | 由网关路由上下文生成 | 适配器生成 | 不接受客户端任意声明 |
| `actor.person_id` | `actor.actor_id` | 重命名 | 账号即真人身份 |
| `context` | `context` | 部分直映 | 子任务和引用需标准化 |
| `request_type=maintain` | `create/write` 等标准类型 | 拆分映射 | 不能保留含义过宽的维护类型 |
| `payload.intent_result` | `tasks[]` | 结构转换 | 应直接接收已确认的确定性任务清单 |

### 3.3 状态映射

| 现有状态 | 平台状态 | 处理方式 |
|---|---|---|
| `accepted` | `accepted` | 直接映射 |
| `in_progress` | `running` | 重命名 |
| `waiting_human` | `waiting_human` | 直接映射 |
| 无独立状态 | `waiting_dependency` | 必须补充 |
| `completed` | `succeeded` | 重命名 |
| `failed` | `failed` | 直接映射 |
| `cancelled` | `cancelled` | 直接映射 |

### 3.4 冲突与缺口

1. 当前是实现参考，不是可独立部署的完整服务，必须增加 HTTP 服务、健康检查和标准回调入口。
2. `flow.start` 要求来源服务直接是 `l2.intent_analysis`，与“所有调用先经业务引擎层接口”冲突；应验证业务引擎层接口服务身份，并通过 `original_source` 保留意图分析来源。
3. 运行状态缺少 `waiting_dependency`。
4. `L12TemplateClient` 直接导入并调用模板管理 Python 类，违反全部接口化原则；必须改为经基础模块层接口调用。
5. 工作台待办/通知当前存在本地 Gateway 类调用路径，正式版必须改为业务应用层通知接口。
6. 当前 JSON 文件仓储仅适合演示；正式异步流程需要事务状态库、inbox/outbox 和回调幂等持久化。
7. 参考 OpenAPI 没有 `operationId`，部分请求体 schema 为空，不能作为正式契约直接发布。

### 3.5 改造结论

- 不能只加外部字段转换器。
- 必须轻量工程化改造：增加 FastAPI 服务壳、标准信封入口、状态映射、`waiting_dependency`、标准回调、HTTP 模板客户端和通知客户端。
- 核心编排算法、节点/依赖/真人任务和回调顺序逻辑可以保留。

---

## 4. 规则计算引擎

### 4.1 实际接口

- 平台入口：`POST /api/v1/instructions`
- 能力发现：`GET /api/v1/capabilities`
- 健康检查：`GET /health`
- 另有本地/管理接口：`/v1/executions`、真人处理、候选技能试算和规则版本接口。

平台公开动作：`rule.evaluate`、`rule.candidate_skill_apply`、`rule.candidate_trial`。

### 4.2 请求映射

| 现有字段 | 平台标准字段 | 处理方式 | 说明 |
|---|---|---|---|
| `protocol_version/message_id/trace_id/request_id` | 同名 | 直接映射 | 现有长度限制允许非 UUID，平台入口必须收紧 |
| `source.layer=L2` | `source.layer=business_engine` | 枚举转换 |
| `source.service_code` | `source.module` | 重命名 |
| `target.service_code=l2.rule_calculation` | `target.capability=rule.calculate` | 能力登记转换 |
| `actor.person_id` | `actor.actor_id` | 重命名 |
| `actor.position_ids/tenant_id` | 同语义字段 | 直接映射 |
| `context.identity_context_ref` | `actor.identity_assertion_id` | 移位 | 由层接口签入 |
| `context.task_id/subtask_id` | 工作流上下文 | 直接映射 |
| `context.data_refs[].ref_id` | `data_refs[].id` | 重命名 |
| `data_refs[].resource_type` | `data_refs[].type` | 枚举转换 |
| `data_refs[].version` | 同名 | 直接映射 |
| `data_refs[].data_labels/allowed_actions` | 权限范围/引用元数据 | 拆分 | 不能信任调用方自行声明授权动作 |
| `payload.requested_capability_code` | `target.capability` | 移位 |
| `payload.business_object_ref` | `parameters.business_object_ref` | 移位 |
| `payload.period` | `parameters.period` | 移位 |
| 当前未显式要求 `rule_ref` | `rule_ref` | 必须补映射 | 正式计算依据不能只靠文本或本地表猜测 |

### 4.3 输出映射

| 现有字段 | 平台标准字段 | 处理方式 |
|---|---|---|
| `reply_type` | `status` | 重命名 |
| `result.result_type=task_receipt` | `task_id/status_url` | 展平 |
| `result.data.state=precondition_query_required` | 流程状态 `waiting_dependency` | 状态转换 |
| `state=waiting_human` | `waiting_human` + `confirmation_ref` | 需创建标准确认引用 |
| 计算结果与验证项 | `data` + `result_ref/evidence_refs` | 结构转换 |
| 小写内部错误码 | 平台大写错误码 | 错误码映射 |

### 4.4 冲突与缺口

1. 平台信封已经较完整，但字段名、层枚举、响应结构和标识符格式与新标准不同。
2. 只允许流程执行引擎调用的边界正确，但真实网络调用应来自业务引擎层接口；需结合服务身份与原始调用方验证。
3. 引擎仍包含本地 SQLite 数据、权限、模型、沙箱、外部系统等模拟适配路径；正式平台必须改成 HTTP 接口客户端。
4. `allowed_actions` 等授权信息不能由流程调用方自证，应以权限模块判定或签名引用为准。
5. 正式输出需要明确 `rule_ref`、公式版本、证据引用、单位和精度。
6. 非平台入口的 `/v1/...` 接口不得被其他模块直接调用；应限制为管理面或经层接口映射。

### 4.5 改造结论

- 第一轮闭环：标准适配器即可调用现有 `/api/v1/instructions`。
- 正式平台：轻微修改，主要是替换本地依赖适配器、增加明确 `rule_ref`/结果引用、收紧调用来源与标识符格式。确定性计算核心可以保留。

---

## 5. 权限模块

### 5.1 实际接口

- 权限判定：`POST /api/permission/check`
- 能力发现：`GET /api/integrations/capabilities`
- 审计查询：`GET /api/permission/audits`
- 预留事件：`POST /api/integrations/events`，当前固定返回 HTTP 501。
- 健康检查：`GET /health`

权限判定已强制只接受基础模块层对内通道的 `mechanism_direct` 请求，并校验调用服务与机制密钥，符合架构中的唯一机制性直达原则。

### 5.2 请求映射

| 现有字段 | 平台标准字段 | 处理方式 | 说明 |
|---|---|---|---|
| `trace_id/request_id` | 同名 | 直接映射 |
| `actor_id` | `actor.actor_id` | 移位 |
| `tenant_id` | `actor.tenant_id` | 移位 |
| `identity_position_ids` | `actor.position_ids` | 重命名 |
| `action` | `action` | 动作字典映射 | 需登记平台标准动作到当前 DataAction |
| `resource_type/resource_id` | `resource.type/id` | 移位 |
| `domain_id` | `scope.domain_id` | 移位 |
| `data_label/data_state` | `scope` 或资源元数据 | 结构转换 | 当前为必填，即使不是数据动作也要伪造值，需调整 |
| `responsible_actor_id` | `actor.actor_id` | 一致性校验 | 当前实现要求二者相同，正确 |
| `executor_type/executor_id` | `delegation` 或执行上下文 | 结构转换 | 智能体不能替代真人主体 |
| `source_service/target_service` | `source.module/target.module` | 重命名 |
| `original_caller_service_id` | 审计中的原始调用方 | 保留 |
| `identity_context_hash` | `actor.identity_assertion_id` 对应的签名摘要 | 适配/校验 |

### 5.3 输出映射

| 现有字段 | 平台标准字段 | 处理方式 | 说明 |
|---|---|---|---|
| `allowed` | `decision=allow/deny` | 布尔转枚举 |
| `result=allow/deny/error` | 判定或接口错误 | 拆分 | `error` 不能伪装成权限拒绝 |
| `decision_id` | 同名 | 直接映射 |
| `reason_code` | 同名 | 直接映射并统一错误码 |
| `reason` | 可读说明 | 重命名/保留 |
| `four_factors` | `details.four_factors` | 移位 |
| 无明确 `policy_version` | `policy_version` | 必须补充 | 不能用空值或猜测值代替 |
| 无 `obligations` | `obligations` | 可选补充 | 首轮可为空；需要脱敏/二次确认时必须由规则返回 |
| `decided_at` | 同名 | 直接映射 |

### 5.4 冲突与缺口

1. 权限请求模型把 `data_label`、`data_state` 设为所有动作必填，不适用于 `platform.enter`、`model.invoke`、`human.confirm` 等通用动作。
2. 响应缺少真实 `policy_version`。
3. 当前只允许单个 `position_id`，同时另有 `identity_position_ids[]`；正式口径应以已验证岗位数组为依据，业务指定岗位只能作为请求上下文。
4. 服务认证方式已经可用，但正式部署建议替换或叠加 mTLS/短期服务令牌，机制密钥不能成为永久唯一凭证。
5. 事件入口未启用是正确的安全默认；幂等、持久化和重放治理完成前不应开启。

### 5.5 改造结论

- 第一轮闭环：基础模块层适配器可完成字段转换并调用现有接口。
- 正式平台：极小修改。放宽数据专属字段为按动作条件必填；响应增加真实 `policy_version`；统一岗位口径。权限判断内核和机制性直达校验可以保留。

---

## 6. 第一轮适配器职责

| 适配器 | 必须完成 |
|---|---|
| `intent-analysis-adapter` | 信封拆包、身份覆盖、超时校验、任务类型查能力字典、标准回复、创建意图确认对象 |
| `workflow-execution-service` | 提供真实 HTTP 服务、标准入口和回调；映射状态；持久化任务与回调幂等 |
| `rule-calculation-adapter` | 标准引用转换、能力动作转换、前置条件转 `waiting_dependency`、结果和错误码标准化 |
| `permission-adapter` | 生成机制性直达请求、动作映射、资源/范围展开、判定结果标准化 |

适配器不得：绕过层接口、复制权限规则、直接读取模块数据库、把客户端身份当成已认证身份，或在失败时自动放行。

## 7. 建议实施顺序

1. 权限适配器：字段最稳定，先打通 `allow/deny/error` 三条路径。
2. 规则计算适配器：现有平台信封最接近标准。
3. 意图分析适配器：补能力编号映射和意图确认对象。
4. 流程执行服务化：完成 HTTP 壳、状态机、回调和接口化依赖。
5. 组合端到端闭环并验证追踪编号、幂等、拒绝和恢复。

## 8. 待负责人确认的问题

- 意图分析的 `task_type → capability_code` 权威映射由谁维护，是否直接进入能力登记中心。
- 流程执行的运行状态库第一阶段是否确定使用 PostgreSQL。
- 规则计算正式 `rule_ref`、`parameter_ref` 和 `data_ref` 的字段归属及版本规则。
- 权限模块的正式策略版本如何生成，是否随每次策略发布单调递增。
