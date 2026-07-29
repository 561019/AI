# L1 1.14 执行沙箱模块说明

## 1. 模块定位

执行沙箱模块给会跑代码、抓网页、做自动化操作的数字员工提供一个独立、隔离、可销毁的执行环境。

本模块解决的问题是：

- AI 临时生成或触发的代码不能直接跑在主系统上。
- 自动化脚本不能随便读宿主机文件、连内网系统、泄露凭据。
- 跑飞的任务不能占满 CPU/内存拖垮机器。
- 网页抓取、代码分析、自动化执行必须可审计、可追踪、可回收。

一句话边界：

```text
1.14 只管“在哪安全地跑”，不管“该不该跑、跑几步”。
```

“该不该跑、跑几步、是否需要真人拍板”归 1.4 驾驭机制。

## 2. 当前交付形态

当前版本是：

```text
Docker 运行时的 L1 1.14 执行沙箱能力包
```

本阶段不再把 Cube Sandbox 作为当前交付阻塞项。Docker 被接受为当前模块的实际运行时，用于完成“可演示、可测试、可验证、后续可被完整平台调用”的能力包交付。

Cube Sandbox / E2B / Firecracker / Kata 作为未来更强隔离运行时选项保留在路线图中。

面向完整平台的调用入口已按层间交互架构 v2.1 补充：

```text
GET  /api/v1/layer-interface/service-catalog
POST /api/v1/layer-interface/requests
GET  /api/v1/layer-interface/requests/{request_id}
GET  /api/v1/layer-interface/requests/{request_id}/events
```

该入口只接受业务引擎层，要求登记引擎、调用凭证和追踪编号，支持即时结果、受理回执、进度事件和拒绝原因。现有 `/api/tasks` 保留为独立 Demo 和兼容接口。

## 3. 面向岗位场景

本能力包重点验证汉和真实岗位场景：

- 财务：发票核销、入库单匹配、坏账准备、所得税估算。
- 供应链/销售：跨部门同时下单超库存预警。
- 采购：采购计划分析、历史数据对比、未来需求预测。
- 市场/运营：上游原料价格每日趋势分析。
- 研发/质量：产品成本测算、BOM 配比异常预警、质量追溯。

推荐主演示场景：

```text
销售/供应链：跨部门同时下单超库存预警
```

该场景可以证明：账号角色、权限检查、mock ERP 数据注入、Docker 沙箱执行、资源限制、结果收集、成本记录、审计留痕和 UI 展示可以形成完整链路。

## 4. 输入

标准任务输入：

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

字段说明：

| 字段 | 含义 |
| --- | --- |
| scenario_id | 场景编号，当前内置 20 个汉和场景模板 |
| actor | 发起人/岗位身份 |
| agent | 数字员工标识 |
| timeout_seconds | 最大运行时间 |
| memory_mb | 内存限制 |
| cpu_cores | CPU 限制 |
| input | 场景输入数据，可为空，部分场景会由 mock ERP/OA 补充测试数据 |

## 5. 输出

标准任务输出：

```json
{
  "id": "task id",
  "status": "success",
  "result": {},
  "logs": [],
  "platform_checks": {},
  "duration_ms": 29
}
```

输出包括：

- 任务状态。
- 业务结果。
- 结果文件路径。
- 沙箱生命周期日志。
- 账号/安全/ERP/OA/成本/审计链路。
- Docker 运行时、CPU/内存/网络等限制证据。

任务状态明确区分 `success`、`denied`、`failed` 和 `timeout`。其中 `denied` 表示权限预检已经终止任务，未创建 Docker 容器；它不是代码执行失败。

## 6. 当前已实现能力

当前已实现并通过 live acceptance 的能力：

| 能力 | 当前状态 | 证明方式 |
| --- | --- | --- |
| Docker 真实执行环境 | 已实现 | `DockerTemplateExecutor`，Docker server `26.1.3` |
| 生命周期与结果收集 | 已实现 | 任务日志包含 request/create/result/destroy，结果写入 `data/results` |
| 宿主机文件隔离 | 已实现 | 容器不能读未挂载宿主机文件，不能写只读 `/app` |
| 资源限制 | 已实现 | CPU/内存/超时参数，跑飞容器被停止 |
| 默认禁止出站 | 已实现 | `--network none` 或内部 Docker 网络 |
| 出站白名单 | 已实现 | Docker 内部网络 + `egress-proxy`，白名单通过、非白名单拒绝、直连绕过失败 |
| 浏览器沙箱 | 已实现 | Headless Chromium 在只读 Docker 浏览器容器中运行并走白名单网关 |
| 凭据注入验证 | 已实现 | 任务只拿短期句柄，通过 broker 使用凭据，明文不进任务容器 |
| 权限前置拦截 | 已实现 | `sales-user` 具备 `inventory:read/order:read`，可执行库存预警；执行发票核销时因缺少 `invoice:read/receipt:read` 返回 `denied`，Docker 未启动且成本为 0 |
| 小界面 Demo | 已实现 | Web UI 支持任务、监控、合规清单、验收演示 |

当前 `/api/acceptance` 结果：

```text
passed: 12
partial: 0
failed: 0
blocked: 0
future: 1
```

其中 `future: 1` 是 Cube Sandbox，作为未来增强项保留，不作为当前交付阻塞。

## 7. 当前限制

- Docker 是容器隔离，共享宿主机内核，隔离强度不等同于 Cube/KVM 微虚拟机。
- 20 个业务场景当前是验证模板，不是每个场景的完整业务系统。
- ERP/OA/CRM/数据库、1.4、1.5、1.9、1.10、1.12 仍是 mock 或接口占位，待完整平台提供真实接口后联调。
- 凭据注入当前是验证 broker，不是企业级 secret manager。
- 不可篡改审计、正式权限策略、正式出站网关策略生命周期仍需平台级服务支持。
