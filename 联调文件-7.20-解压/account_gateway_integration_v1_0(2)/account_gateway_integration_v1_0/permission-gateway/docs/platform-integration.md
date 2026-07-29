# 平台全模块集成契约

依据《汉和 AI 平台四层架构图 v3.0》，权限模块对其它模块只提供一套统一权限契约，不按业务模块复制权限引擎或权限数据。

## 通用调用路径

| 通道 | 状态 | 接口 | 调用时机 |
|---|---|---|---|
| 运行期检查 | 已启用 | `POST /api/permission/check` | 任何读取、写入、执行、导出、生成或审批动作前 |
| 权限事实同步 | 已启用，经账号网关 | `/api/org/*`、`/api/permissions/*` | 人岗、资源、数据、动作、服务关系和规则发生变化时 |
| 决策审计查询 | 已启用 | `GET /api/permission/audits` | 安全合规、审计、排错和对账 |
| 异步事件入口 | 已预留，返回 501 | `POST /api/integrations/events` | 未来资源/数据/工作流生命周期事件；v1 禁止写入 |
| 能力发现 | 已启用 | `GET /api/integrations/capabilities` | 新模块接入前读取版本、通道、模块 ID 和启用状态 |

第一阶段默认本机可信网络。业务模块通过账号网关或批准的服务身份进入权限模块；跨主机部署前必须启用 mTLS 或等价服务认证。

## 统一请求规则

1. 每次业务动作调用 `POST /api/permission/check`，带 `actor_id + action + data_label + data_state` 四要素和 `source_service/target_service`。
2. `actor_id` 必须来自 JWT 实名账号，且 `user_id = actor_id = person_id`。
3. 新动作先由 DSM/管理员通过 `register_data_action` 登记；新服务关系先通过 `create_service_call_rule` 允许。
4. 涉及具体数据、转授或数据登记时必须提供稳定 `resource_id`。
5. HTTP 非 200、`allowed=false` 或 `result=error` 都是拒绝执行；不得使用缓存或本地规则自行放行。
6. 同一业务链复用 `trace_id`，每次调用使用新的 `request_id`。

## L1 基础模块

| 模块 | `source_service` | 调用权限模块 | 预留异步事件前缀 |
|---|---|---|---|
| 1.2 流程管控 | `workflow_control` | 工作流启动、流转、审批前检查；审批模板和岗位事实经网关同步 | `workflow.instance.*` |
| 1.3 进化机制 | `evolution_engine` | 规则/提示词/方案变更前检查 | `evolution.rule.*` |
| 1.4 驾驭机制 | `governance_control` | 制度发布、治理动作和高风险变更前检查 | `governance.policy.*` |
| 1.5 大模型调度 | `model_orchestrator` | 模型调用、模型配置读写、额度相关动作前检查 | `model.invocation.*` |
| 1.6 上下文与提示词管理 | `context_prompt` | 上下文读取、提示词模板读写前检查 | `prompt.template.*` |
| 1.7 数据 | `data_platform` | 数据登记、读取、写入、导出前检查；数据动作和状态经网关同步 | `data.record.*` |
| 1.8 账号网关 | `account_gateway` | JWT 主体适配、组织/权限聚合代理、旧 `/auth/validate` 兼容 | `identity.account.*` |
| 1.9 安全合规 | `security_compliance` | 按 trace/actor/time 拉取权限审计；合规动作前检查 | `security.finding.*` |
| 1.10 设备与系统接口 | `device_system_adapter` | 设备/外部系统资源连接和操作前检查 | `device.resource.*` |
| 1.11 人机协同 | `human_machine` | 任务分派、确认、接管和协同操作前检查 | `task.assignment.*` |
| 1.12 成本管控 | `cost_control` | 成本记录读取、预算审批和配额变更前检查 | `cost.record.*` |
| 1.13 Agent 知识库 | `agent_knowledge` | 知识文档读取、写入、索引和授权前检查 | `knowledge.document.*` |
| 1.14 Agent 执行沙箱 | `agent_sandbox` | Agent 工具执行、文件访问和结果导出前检查 | `sandbox.execution.*` |
| 1.15 Agent 记忆管理 | `agent_memory` | 记忆读取、写入、删除和共享前检查 | `memory.record.*` |

## L2 业务引擎

| 引擎 | `source_service` | 典型受控动作 | 预留异步事件前缀 |
|---|---|---|---|
| 文档表格解析 | `document_table_parser` | `document.parse.*` | `document.parse.*` |
| 外部系统对接 | `external_system_connector` | `external.sync.*` | `external.sync.*` |
| 数据归集聚合 | `data_aggregation` | `data.aggregate.*` | `data.aggregate.*` |
| 规则计算 | `rule_engine` | `rule.calculate.*` | `rule.calculate.*` |
| 分析预测 | `analytics_forecast` | `analysis.forecast.*` | `analysis.forecast.*` |
| 知识库问答 | `knowledge_qa` | `knowledge.answer.*` | `knowledge.answer.*` |
| 内容产出 | `content_generation` | `content.generate.*` | `content.generate.*` |
| 多媒体生成 | `multimedia_generation` | `media.generate.*` | `media.generate.*` |
| 人机交互 | `human_machine_engine` | `interaction.session.*` | `interaction.session.*` |
| 数据可视化 | `data_visualization` | `visualization.render.*` | `visualization.render.*` |

## L4 企业业务界面

L4 使用 `source_service=business_application`。界面本身不保存权限矩阵；每个按钮、批量操作和后台任务都由相应业务服务在实际执行前发起权限检查。界面可通过受控的权限快照显示可用能力，但快照只用于展示和对账，不得替代运行期检查。

## 事件预留约束

`POST /api/integrations/events` 已固定请求包络：`event_id`、`event_type`、`occurred_at`、`source_service`、`tenant_id`、可选 `actor_id/resource_type/resource_id` 和 `payload`。

v1 该地址固定返回 `501 INTEGRATION_EVENT_NOT_ENABLED`，不会写入权限库。启用前必须完成服务认证、事件幂等、持久化、重放、死信和审计治理；当前事实同步统一走账号网关代理的聚合管理接口。
