# 平台模块接入清单

本清单按 `架构/层间交互逻辑图_v2_7_20260718-1.html` 重新分层。

原则：

- L2 业务引擎层：负责理解、编排、办理业务任务。
- L1 基础模块层：负责权限、模型、账号、数据、知识、上下文、沙箱等底层能力。
- 文档表格解析属于 L2 业务引擎。
- 知识库问答属于 L2 业务引擎；知识库本体属于 L1 基础模块。
- 切分、向量化、检索、重排不再作为架构图顶层模块，归入 L1 知识库内部基础能力。

## L2 业务引擎层：十四个业务引擎

| 架构模块 | 服务名 | 端口 | 平台标准入口 | 主要能力 |
|---|---|---:|---|---|
| 意图分析引擎 | intent | 8000 | `/api/v1/intent/analyze` | `intent.analyze` |
| 流程执行引擎 | workflow | 8020 | `/api/v1/workflows/executions` | `workflow.execute` |
| 内容产出引擎 | content | 8011 | `/api/v1/content/instructions` | `content.generate` |
| 文档表格解析引擎 | document_table_parsing | 8036 | `/api/v1/document-table/instructions` | `document.parse`, `document.table.extract`, `document.package.build` |
| 数据操作引擎 | data_operation | 8031 | `/api/v1/data-operation/instructions` | `data.collect`, `data.consolidate`, `data.search`, `data.persist`, `data.trace`, `data.read/create/update/delete/aggregate` |
| 规则计算引擎 | rule | 8010 | `/api/v1/rules/instructions` | `rule.calculate` |
| 分析预测引擎 | analysis_prediction | 8030 | `/api/v1/analysis/instructions` | `analysis.financial_statement`, `analysis.price_forecast`, `analysis.business_metric` |
| 监控提醒引擎 | monitoring_reminder | 8034 | `/api/v1/monitoring/instructions` | `monitor.*`, `reminder.*` |
| 项目管理引擎 | project_management | 8033 | `/api/v1/projects/instructions` | `project.*` |
| 外部系统对接引擎 | external_system_integration | 8037 | `/api/v1/external-systems/instructions` | `external.system.invoke`, `external.api.call`, `external.callback.handle` |
| 知识库问答引擎 | knowledge_qa | 8038 | `/api/v1/knowledge-qa/instructions` | `knowledge.query`, `knowledge.qa.answer`, `knowledge.qa.contextual_answer` |
| 数字资产引擎 | digital_asset | 8032 | `/api/v1/assets/instructions` | `asset.*`, `skill.*`, `knowledge_source.*` |
| 知识地图引擎 | knowledge_map | 8039 | `/api/v1/knowledge-map/instructions` | `knowledge_map.*` |
| 多媒体生成引擎 | multimedia_generation | 8035 | `/api/v1/multimedia/instructions` | `multimedia.generate`, `multimedia.poster.plan`, `multimedia.text_to_image` |

## L1 基础模块层：十五个基础模块

| 架构模块 | 服务名 | 端口 | 平台标准入口 | 主要能力 |
|---|---|---:|---|---|
| 权限管理 | permission | 8001 | `/api/v1/permissions/check` | `permissions.check` |
| 大模型调度 | model | 8002 | `/api/v1/models/responses` | `model.respond` |
| 流程模板管理 | template | 8004 | `/api/v1/templates/instructions` | `template.*` |
| 上下文与提示词管理 | context_prompt_management | 8059 | `/api/v1/context-prompts/instructions` | `context.*`, `prompt.*` |
| 数据 | foundation_data | 8060 | `/api/v1/foundation-data/instructions` | `foundation_data.*` |
| 账号网关 | account_gateway | 8050 | `/api/v1/accounts/instructions` | `account.*` |
| 人机协同 | human_collaboration | 8052 | `/api/v1/human/instructions` | `human.task.*` |
| 进化机制 | evolution_mechanism | 8054 | `/api/v1/evolution/instructions` | `evolution.*` |
| 驾驭机制 | control_mechanism | 8061 | `/api/v1/control/instructions` | `control.*` |
| 知识库 | knowledge_base | 8055 | `/api/v1/knowledge/instructions` | `knowledge.retrieve`, `knowledge.material.get`, `chunk.*`, `vector.*`, `search.*` |
| 执行沙箱 | execution_sandbox | 8053 | `/api/v1/sandbox/instructions` | `sandbox.*` |
| 记忆管理 | memory_management | 8062 | `/api/v1/memory/instructions` | `memory.*` |
| 设备与系统接口 | device_system_interface | 8063 | `/api/v1/device-systems/instructions` | `device.*`, `system.*` |
| 安全合规 | security_compliance | 8051 | `/api/v1/security/instructions` | `security.*` |
| 成本管控 | cost_control | 8064 | `/api/v1/cost/instructions` | `cost.*`, `usage.*` |

## 启动和查看

启动整套平台：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\framework\start_all.ps1
```

查看端口状态：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\framework\status_all.ps1
```

查看全部能力：

```text
http://127.0.0.1:8400/api/v1/capabilities
```

查看调用链：

```text
http://127.0.0.1:8100/api/v1/traces/{trace_id}/calls
```

全模块接口验收页面：

```text
http://127.0.0.1:8100/modules
```

页面会逐个调用每个模块的安全代表能力，并展示：

- 平台标准接口请求 Request
- 平台标准接口响应 Response
- trace 调用链
- 调用链中每个模块接收到的内容和输出的内容
- 真实交付模块未启动时的 `UPSTREAM_UNAVAILABLE` 提示
