# 数据操作引擎联调包

版本：v0.6.0（2026-07-29）

这是符合《模块统一接入与交付规范》的最小可运行模块包。它不是前端演示工程，也不接收 L4 直连；只接收 **流程执行引擎** 派发的标准 `task.dispatch`，再由数据操作引擎按当前真人、数据范围和动作执行受控数据操作。

## 1. 能力与边界

| 能力 | 作用 |
| --- | --- |
| `data.collect` / `data.persist` | 业务数据收集、登记、打标签，经 L1.7 固定存档并返回 `data_ref`。 |
| `data.consolidate` | 基于两个及以上 `source_data_refs` 整合并登记新的业务数据对象。 |
| `data.search` | 从 L1.7 受控读取业务数据，返回 `business_result`、`evidence`、`raw_access` 三层结果。 |
| `data.read` / `data.trace` | 按 `data_ref` 读取内容/版本或追溯登记与审计。 |
| `data.update` / `data.delete` | 版本更新和逻辑删除；旧版本与审计证据不被覆盖。 |

本模块不做意图分析、流程编排、同层直调、比例计算、趋势分析、归因、诊断或预测。后四类分别属于规则计算或分析预测引擎。

特别说明：规范示例中的 `data.aggregate` 不在本模块公开能力清单中。它会把分析统计边界重新混淆。基础的筛选、分组、计数、求和通过 `data.search` 返回受控 `business_result`；比例、趋势、诊断、预测必须改派对应引擎。

## 2. 目录与启动

```text
data_operation_engine/
  README.md
  manifest.json
  service.py
  engine.py
  storage_adapters.py
  nl_parser.py
  contracts/
  samples/
  tests/
```

仅使用 Python 标准库。Windows PowerShell 启动：

```powershell
cd "C:\Users\chen3\Desktop\实习项目\数据操作引擎联调包\data_operation_engine"
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

`--reset` 只清理本包的 `data/` 本地模拟数据，不会触碰项目外文件。首次联调可使用；保留数据重启时运行 `python .\service.py --port 8031`。

健康检查：`GET http://127.0.0.1:8031/health`  
模块发现：`GET http://127.0.0.1:8031/manifest`  
标准派单：`POST http://127.0.0.1:8031/api/v1/data-operation/instructions`

## 3. 标准请求与响应

请求完整字段见 `contracts/input.schema.json`。关键约束：

- `source` 必须是 `business_engine/workflow-execution`，因此 L4、前端和其他 L2 引擎不能直连本模块。
- `target` 必须是 `business_engine/data-operation`，且 `target.capability` 必须等于 `action`。
- 必须携带已认证的 `actor.tenant_id`、`actor.user_id`，以及 `context.account_id`、`context.project_id`。
- 写操作必须携带 `idempotency_key`。
- `data.search` 还必须在 `payload.business_context` 中提供 `permission_decision_id`，并提供明确的公司范围和 `query_spec`。

`sync` 模式返回终态 `success` 或 `failed`；`async` 模式先返回 `accepted + task_id + status_url`。无论哪种模式，模块内部都保留同一 `trace_id`、任务记录和对流程执行引擎的 reference-first 回调。

同步存档示例见 `samples/sample_request.json`，真实返回结构见 `samples/sample_response.json`。运行请求时，`data_ref` 和 L1.7 位置会动态生成，不能硬编码为样例中的占位符。

## 4. 联调最小步骤

1. 启动服务后，用 `samples/sample_request.json` 发起一次 `data.persist`。
2. 检查响应：必须有 `status=success` 和动态生成的 `data.data_ref`。
3. 使用同一 `data_ref` 由流程执行引擎发起 `data.read` 或 `data.trace`。
4. 对结构化取数，用 `data.search` 派单；流程执行和内容产出只能以 `business_result` 为主结果，`evidence` 用于追溯，`raw_access` 仅供受控复核。
5. 打开 `status_url`，核对请求、终态、L1.7 模拟调用和审计链是否共享同一 `trace_id`。

## 5. 本地实现边界

本包包含 SQLite 形式的 L1.7 本地模拟适配器，用于验证链路、审计和协议，不代表已经接入平台真实数据模块、身份、权限或安全服务。真实平台联调时，应将这些适配器替换为平台网关/服务调用，保持本包的标准接口不变。
