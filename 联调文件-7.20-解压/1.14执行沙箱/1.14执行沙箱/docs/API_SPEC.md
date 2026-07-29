# 接口说明

## 平台正式联调入口（推荐）

依据平台层间交互逻辑 v2.1，执行沙箱属于基础模块层，只接受业务引擎层经层接口发起的请求。新增接口：

```text
GET  /api/v1/layer-interface/service-catalog
POST /api/v1/layer-interface/messages
GET  /api/v1/layer-interface/messages/{request_id}
```

新平台联调使用公司标准消息信封，按 `capability_id + action` 选择能力，并返回 `accepted / success / failed`。旧 `/requests` 接口只用于兼容测试。完整请求与响应契约见 `docs/COMPANY_STANDARD_INTERFACE.md`。

以下 `/api/tasks`、`/api/e2b/*` 和验收接口继续保留，用于当前独立 Demo、测试和兼容调用。

## GET /api/health

服务健康检查。

## GET /api/scenarios

返回 20 个汉和场景模板。

## POST /api/tasks

创建并执行一个沙箱任务。

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

返回任务详情，包括任务状态、业务结果、日志、平台检查、运行限制和审计信息。

任务状态取值：

- `queued`：排队中。
- `running`：正在执行前置检查或沙箱任务。
- `success`：Docker 沙箱执行成功。
- `denied`：权限前置检查拒绝，Docker 执行器未调用，资源成本为 0。
- `failed`：已允许执行，但执行过程发生错误。
- `timeout`：任务超过运行时长限制并被停止。

权限拒绝时，`platform_checks.sandbox_execution.started=false`，日志包含 `sandbox.not_started`、`sandbox.denied` 和 `cost.skipped`，不包含 `sandbox.created` 或 `sandbox.destroyed`。

## GET /api/tasks

返回任务列表。

## GET /api/tasks/{task_id}

返回单个任务详情，包括：

- input
- result
- logs
- platform_checks
- limits
- audit
- executor
- egress_policy

## GET /api/policy

返回当前运行策略，包括：

- 当前执行器：`DockerTemplateExecutor`
- Docker 镜像
- 浏览器镜像
- 出站策略
- 相邻模块占位接口

## GET /api/readiness

返回就绪检查：

- 场景是否加载。
- 任务存储是否可用。
- 结果目录是否可用。
- Docker 执行器是否可用。

## GET /api/compliance

返回当前交付范围合规清单。

当前口径：

```text
Docker is accepted as the current L1 1.14 sandbox runtime.
Cube is a future stronger isolation option, not a current delivery blocker.
```

返回内容包括：

- 当前交付范围已完成项。
- 待真实平台联调项。
- 未来增强项。
- 下一步交付建议。

## GET /api/acceptance

返回客观验收状态。

当前结果应为：

```text
passed: 12
partial: 0
failed: 0
blocked: 0
future: 1
```

12 个 passed 项：

- sandbox lifecycle
- result collection
- real container isolation
- host file isolation
- resource timeout
- egress allowlist
- browser sandbox
- credential injection
- E2B-like adapter
- Hanhe role scenario E2E
- Hanhe finance invoice E2E
- Hanhe purchase plan E2E

`future: 1` 是 Cube Sandbox。

## GET /api/verification

返回可点击 live proof 用例列表。

当前包括：

- `docker_runtime`
- `docker_task`
- `host_file_isolation`
- `resource_timeout`
- `network_default_deny`
- `egress_allowlist_gateway`
- `browser_sandbox`
- `permission_denial`
- `credential_injection`
- `e2b_like_adapter`
- `hanhe_role_scenario_e2e`
- `hanhe_finance_invoice_e2e`
- `hanhe_purchase_plan_e2e`

## POST /api/verification/run

运行一个或全部 live proof。

请求示例：

```json
{"case_id":"credential_injection"}
```

也可以运行全部：

```json
{"case_id":"all"}
```

返回内容包括：

- 验证项标题。
- 要证明的能力。
- 预期结果。
- 实际命令/API 调用。
- stdout/stderr 或任务结果。
- passed/failed 状态。

`browser_sandbox` 的 `evidence.assertions` 直接给出：

- `allowlisted_page_loaded`：白名单受控页面是否真实加载。
- `non_allowlisted_blocked`：代理日志是否记录非白名单 `allowed=false`。
- `direct_bypass_blocked`：未配置代理时 Chromium 是否只得到 `ERR_/offline` 错误页。

不能仅凭 Chromium 的 `returncode` 判断网页访问是否成功，因为 Chromium 成功渲染 HTTP 403 拦截页或离线错误页后也可能返回 0。

## POST /api/verification/report

运行全部 live proof，并把本次验证结果落盘为 JSON 和 Markdown 报告。

返回示例：

```json
{
  "status": "done",
  "json": "docs/evidence/reports/verification-report-20260707-120000.json",
  "markdown": "docs/evidence/reports/verification-report-20260707-120000.md",
  "summary": {"passed": 11, "failed": 0}
}
```

## GET /api/verification/reports

列出已经归档的现场验证报告。

## POST /api/verification/concurrency-report

运行保守小并发测试，并把结果落盘为 JSON 和 Markdown 报告。

默认运行 3 个 Docker 沙箱任务；可传 `count`，服务端限制为 1 到 6，避免给演示服务器造成不必要压力。

请求示例：

```json
{"count": 3}
```

返回内容包括：

- 请求任务数。
- 成功/失败数。
- 总耗时。
- 每个任务的任务编号、执行器、耗时和业务结果。

## GET /api/files/{relative_path}

下载结果文件。

## 旧版 L2 调用方式（兼容保留）

L2 引擎后续可以按以下方式调用：

1. 调用 `POST /api/tasks` 创建沙箱任务。
2. 通过返回值或 `GET /api/tasks/{task_id}` 获取执行结果。
3. 读取 `logs`、`platform_checks`、`result` 判断任务结果和安全链路。
4. 若需要下载文件，通过 `/api/files/{relative_path}` 获取。

新平台联调不应再直接使用该简化请求格式，应使用 `/api/v1/layer-interface/requests`。本模块不决定业务流程是否应该发起；1.4 和 1.9 应在调用前给出上游策略，沙箱仍会执行运行前的最终权限与安全检查。
## E2B-like Docker 适配器接口

这些接口不是 Cube 原生 E2B，也不是完整 E2B SDK 兼容实现。它们是在当前 Docker 运行时上提供的 E2B-like 会话接口，方便 L2 引擎后续按“创建沙箱、运行任务、查询结果、销毁沙箱”的方式调用。

### GET /api/e2b/capability

返回适配器能力说明。

### POST /api/e2b/sandboxes

创建一个 Docker-backed 沙箱会话。

请求示例：

```json
{
  "actor": "sales-user",
  "agent": "l2-agent",
  "timeout_seconds": 10,
  "memory_mb": 512,
  "cpu_cores": 1,
  "metadata": {"caller": "L2 workflow engine"}
}
```

### GET /api/e2b/sandboxes

列出沙箱会话。

### GET /api/e2b/sandboxes/{sandbox_id}

查询单个沙箱会话和已运行任务。

### POST /api/e2b/sandboxes/{sandbox_id}/run

在会话中运行一个已注册场景模板。底层仍走 `DockerTemplateExecutor`。

请求示例：

```json
{
  "scenario_id": "s19_over_stock_warning",
  "actor": "sales-user",
  "input": {}
}
```

### POST /api/e2b/sandboxes/{sandbox_id}/destroy

销毁会话。当前 Docker 执行是一次性任务容器，接口会将会话状态标记为 `destroyed`。


## 交付包接口

### GET /api/delivery/checklist

返回 L1 1.14 能力包交付清单，包括模块说明、边界、输入输出、接口、小界面 Demo、测试数据、测试用例、测试结果、截图证据、当前限制和联调准备表。

当 `docs/evidence/*` 证据文件全部存在时，截图/证据项会从 `ready` 变为 `done`。

### GET /api/delivery/evidence

返回正式证据包文件清单，包括 UI 截图、API 快照、文件路径、存在状态、更新时间和证明点。

### GET /api/delivery/package

返回完整交付包摘要，组合以下内容：

- `checklist`
- `evidence`
- `export`
- `role_scenario`
- `integration_contracts`

### POST /api/delivery/export

生成或刷新正式证据包：

```text
docs/evidence/delivery-package.zip
```

zip 包包含：

- `delivery-package.json`
- README 和 docs 交付文档
- `docs/evidence/*` 截图和 API 快照
- `docs/evidence/reports/*` 验证报告

### GET /api/delivery/export.zip

下载最新证据包。若 zip 不存在，接口会先生成再返回。

### GET /api/delivery/role-scenario

返回推荐汉和真实岗位场景：

```text
销售/供应链跨部门同时下单超库存预警
```

该接口明确输入、mock 业务数据、预期输出和证明点。

### GET /api/delivery/integration-contracts

返回 1.4、1.5、1.8、1.9、1.10、1.12 和 L2 的联调边界与调用准备说明。
