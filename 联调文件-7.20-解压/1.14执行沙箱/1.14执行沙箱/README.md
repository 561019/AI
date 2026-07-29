# Agent Execution Sandbox Capability Package

这是 L1 1.14「执行沙箱」模块能力包。

当前交付口径：

```text
Docker 运行时的 L1 1.14 执行沙箱能力包
```

本模块只负责“在哪里安全地跑”，不负责决定“该不该跑”。是否允许执行、最大步数、人工审批等由 1.4 驾驭机制负责。

## 当前已实现

- Web 小界面 Demo。
- 20 个汉和场景模板。
- 任务提交、执行、查询。
- Docker 真实隔离执行器。
- 公司标准消息信封接口：L2 -> L1，携带 `message_id`、`trace_id`、`capability_id`、真人、租户、流程上下文、版本、截止时间和幂等键。
- AI 临时代码隔离运行：L2 可提交 Python 程序；容器默认断网、只读、禁止提权、限制进程数、CPU、内存和运行时长。
- 动态浏览器隔离采集：L2 可提交白名单 URL；后端为每次请求创建内部网络、egress-proxy、Chromium 容器、结果目录和出站审计。
- 按需保留不可变证据快照：记录运行时、日志和结果文件 SHA256，不保留可继续运行的容器。
- 公司/租户范围隔离：请求携带 `actor.tenant_id`，任务结果和查询按公司范围保护。
- CPU/内存/超时限制。
- 宿主机文件隔离验证。
- 默认禁止出站。
- Docker egress-proxy 出站白名单验证。
- Headless Chromium 浏览器沙箱验证。
- 凭据 broker / 短期句柄验证。
- mock 账号网关、mock 安全合规、mock ERP/OA、mock 成本管控、mock 审计。
- 任务日志、结果文件、监控页、合规清单、验收演示页。
- 正式交付证据包、截图/API 快照、验证报告、并发测试报告。
- 三个汉和岗位场景 E2E：销售/供应链超库存、财务发票核销、采购计划分析。

当前验收：

```text
GET /api/acceptance
passed: 12
partial: 0
failed: 0
blocked: 0
future: 1
```

`future: 1` 是 Cube Sandbox。Cube 作为未来更强隔离运行时，不作为当前 Docker 交付阻塞。

## 启动

服务器当前运行路径：

```bash
cd /home/nlp/刘卓/执行沙箱
SANDBOX_MVP_HOST=0.0.0.0 SANDBOX_MVP_PORT=8765 python3 backend/app.py
```

访问：

```text
http://10.60.66.97:8765/
```

## 正式平台联调 API

公司《数据流转、对接与通信交互规范》v0.3 对应的正式联调入口：

```text
POST /api/v1/layer-interface/messages
GET  /api/v1/layer-interface/messages/{request_id}
GET  /api/v1/layer-interface/service-catalog
```

正式请求必须由 L2 发往 L1，并使用完整标准消息信封：

```text
source.layer = L2
target.layer = L1
target.service_code = l1.execution_sandbox
route_type = task.dispatch
```

| capability_id | action | 作用 |
| --- | --- | --- |
| `CAP.SANDBOX.TASK.RUN` | `sandbox.template.run` | 运行已登记岗位场景模板。 |
| `CAP.SANDBOX.CODE.RUN` | `sandbox.code.run` | 隔离运行 AI 临时生成的 Python 程序。 |
| `CAP.SANDBOX.BROWSER.RUN` | `sandbox.browser.run` | 在白名单网络策略下隔离采集网页。 |

标准回复：`accepted`（已受理长任务）、`success`（已完成）、`failed`（拒绝/失败/超时）。完整字段、三类请求示例、查询方法和错误码见 `docs/COMPANY_STANDARD_INTERFACE.md`。

## 兼容与演示 API

```text
GET  /api/v1/layer-interface/service-catalog
POST /api/v1/layer-interface/requests
GET  /api/v1/layer-interface/requests/{request_id}
GET  /api/v1/layer-interface/requests/{request_id}/events
GET  /api/health
GET  /api/scenarios
POST /api/tasks
GET  /api/tasks
GET  /api/tasks/{task_id}
GET  /api/policy
GET  /api/readiness
GET  /api/compliance
GET  /api/acceptance
GET  /api/verification
POST /api/verification/run
POST /api/verification/report
POST /api/verification/concurrency-report
POST /api/delivery/export
GET  /api/delivery/export.zip
```

`/api/v1/layer-interface/requests`、`/api/tasks` 与 `/api/e2b/*` 保留用于旧网站、独立 Demo 和兼容测试；新平台联调必须使用上方的 `/messages` 标准接口。

详细说明：

- `docs/LAYER_ARCHITECTURE_ALIGNMENT.md`
- `docs/PLATFORM_INTERFACE_SPEC.md`
- `docs/COMPANY_STANDARD_INTERFACE.md`

## 推荐演示场景

```text
跨部门同时下单超库存预警
```

请求示例：

```json
{
  "scenario_id": "s19_over_stock_warning",
  "actor": "sales-user",
  "agent": "demo-agent",
  "timeout_seconds": 10,
  "memory_mb": 512,
  "cpu_cores": 1,
  "input": {}
}
```

该场景证明：销售岗位权限、ERP 库存/订单数据、Docker 沙箱执行、超库存预警、成本记录、审计留痕和 UI 展示能形成完整链路。

已补充 E2E 场景：

- 财务发票核销：`s04_invoice_matching`，actor `demo-user`。
- 采购计划分析：`s20_purchase_plan`，actor `demo-user`。

## 验证命令

```bash
curl http://127.0.0.1:8765/api/readiness
curl http://127.0.0.1:8765/api/acceptance
curl http://127.0.0.1:8765/api/compliance
curl -H 'Content-Type: application/json' -d '{"case_id":"credential_injection"}' http://127.0.0.1:8765/api/verification/run
```

## 当前限制

- Docker 是容器隔离，共享宿主机内核；Cube/KVM 微虚拟机可作为未来更强隔离升级。
- 20 个场景是验证模板，不是完整业务系统。
- 真实 1.4、1.5、1.8、1.9、1.10、1.12 还未接入；当前身份、权限、安全、ERP/OA 和成本为 Mock 或适配器。
- `data_refs/artifact_refs` 的正式解析、`decision_id`、安全义务和不可篡改审计需要由 L1.1、L1.7、L1.8、L1.9 接入。
- 当前凭据 broker 是机制验证，不是企业级 secret manager。
- 平台接口当前使用演示共享 token；正式生产需由统一接口控制模块和服务身份替换。
- 标准接口当前以 `accepted` 后查询结果为主；主动 `flow.callback` 投递、失败补偿和流程恢复需与 L2 流程执行及监控提醒引擎联调。
- 正式生产还需要不可篡改审计、统一身份、正式策略中心和运维监控。
