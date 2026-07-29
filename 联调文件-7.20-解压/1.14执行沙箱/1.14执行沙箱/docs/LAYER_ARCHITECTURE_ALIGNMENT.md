# 执行沙箱与平台层间交互架构对齐说明

依据：`层间交互逻辑图_v2_1_20260712.html`。

## 1. 架构结论

执行沙箱属于基础模块层，只提供被调用能力，不主动调用业务应用层或业务引擎层。

标准调用链为：

```text
业务应用层
  -> 业务引擎层请求接收端
  -> 流程执行引擎或执行引擎
  -> 业务引擎层请求发起端
  -> 基础模块层请求接收端
  -> execution_sandbox.run_task
  -> DockerTemplateExecutor
  -> 结果 / 受理回执 / 拒绝及原因
```

业务应用层不能直接调用执行沙箱。当前能力包新增的 `v1/layer-interface` API 是基础模块层接口控制模块尚未交付前的兼容适配入口；完整平台建成后，应由基础模块层统一接口控制模块路由到同一服务能力。

## 2. 架构要求与实现映射

| 架构要求 | 执行沙箱实现 |
| --- | --- |
| 唯一入口 | `POST /api/v1/layer-interface/requests` |
| 仅接收业务引擎层 | `X-Caller-Layer` 必须为 `business_engine` |
| 准入名单校验 | `X-Engine-Id` 必须属于 13 个已登记业务引擎之一 |
| 调用身份校验 | Bearer token；请求头与请求体 caller 必须一致 |
| 追踪编号贯穿 | `X-Trace-Id` 与 `body.trace_id` 必须一致，写入任务审计 |
| 服务目录 | `GET /api/v1/layer-interface/service-catalog` |
| 按服务编号分派 | 当前登记 `execution_sandbox.run_task` |
| 即时结果 | `reply_mode=immediate`，请求完成后返回 `reply_type=result` |
| 受理回执 | `reply_mode=receipt`，先返回 202 和 `request_id` |
| 进度与结果查询 | `GET /requests/{request_id}` 与 `/events` |
| 拒绝及原因 | 统一 `reply_type=rejection`，返回原因编码和细节 |
| 留痕与用量 | 平台请求事件、任务日志、审计事件、CPU/内存/耗时和成本字段 |
| 重复请求保护 | 相同 `trace_id` 和相同内容返回原请求；内容不同返回 409 |

## 3. 执行沙箱公开能力

当前只向服务目录登记一个正式能力：

```text
execution_sandbox.run_task
```

该服务负责：

- 接收已结构化的场景任务。
- 对发起人和场景执行权限预检。
- 应用 CPU、内存、时长、只读和网络策略。
- 在 Docker 容器中执行任务。
- 返回业务结果、结果文件和执行证据。
- 记录任务状态、日志、审计和用量。

调用方不需要知道 `DockerTemplateExecutor`、egress proxy、credential broker 或结果目录等内部实现。

## 4. 当前真实边界

已经真实实现：

- 架构对齐请求信封、调用方层级校验、引擎准入名单、追踪编号和幂等检查。
- 即时结果、异步受理回执、状态查询、进度事件和标准拒绝。
- Docker 真实隔离执行、资源限制、结果回收和任务证据。

仍需平台联调：

- Bearer token 当前是演示共享令牌，生产环境必须接统一身份和服务凭证。
- 真人身份与权限当前由 mock 账号网关和 mock 安全合规提供，后续接 1.8、权限管理和 1.9。
- ERP/OA 数据和成本字段当前仍为 mock，后续接 1.10 和 1.12。
- 主动通知/回调通道尚未接监控提醒引擎；当前通过轮询查询进度和结果。
- 当前服务目录由本能力包提供；完整平台应由基础模块层统一接口控制模块集中登记和分派。

## 5. 与旧接口的关系

`POST /api/tasks`、`GET /api/tasks/{id}` 和 `/api/e2b/*` 保留用于独立 Demo、验收和兼容测试。

平台联调应优先使用：

```text
GET  /api/v1/layer-interface/service-catalog
POST /api/v1/layer-interface/requests
GET  /api/v1/layer-interface/requests/{request_id}
GET  /api/v1/layer-interface/requests/{request_id}/events
```
