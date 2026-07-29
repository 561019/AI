# L1.14 执行沙箱公司标准接口说明

**接口规范依据：**《数据流转、对接与通信交互规范》v0.3（2026-07-17）  
**能力模块：**L1.14 执行沙箱  
**调用方向：**L2 业务引擎层 -> L1 基础模块层  
**正式状态：**可联调；当前 Docker 运行时真实可用。  
**说明：**本文规定新平台联调的正式接口。旧 `/api/v1/layer-interface/requests`、`/api/tasks` 仅用于历史兼容和独立演示，不得作为新平台接入入口。

## 1. 真实地址与调用顺序

当前联调服务器：

```text
http://10.60.66.97:8765
```

调用方是 L2 中需要运行程序或浏览器操作的业务引擎，通常是流程执行引擎。调用顺序：

```text
L2 流程执行引擎
  -> POST /api/v1/layer-interface/messages
  -> accepted（长任务受理）或 success/failed
  -> GET /api/v1/layer-interface/messages/{request_id}
  -> success 或 failed
  -> L2 以 flow.callback 恢复自己的流程节点
```

L4 业务应用层不得直接调用本接口。执行沙箱不决定业务是否应执行，也不处理模型推理；L2 应先完成流程编排、行为控制、权限和安全决策，再投递已登记的沙箱任务。

## 2. HTTP 接口清单

| 方法 | 路径 | 用途 | 正式性 |
| --- | --- | --- | --- |
| `GET` | `/api/v1/layer-interface/service-catalog` | 查询公司标准优先的能力目录、能力编号、动作、标准入口和兼容接口边界 | 正式发现接口 |
| `POST` | `/api/v1/layer-interface/messages` | 按公司标准信封提交任务 | **正式调用入口** |
| `GET` | `/api/v1/layer-interface/messages/{request_id}` | 查询长任务最终结果 | **正式查询入口** |

## 3. 鉴权与请求头

所有正式请求必须带：

```http
Authorization: Bearer <platform-token>
Content-Type: application/json
```

当前服务器联调 token 由部署人员配置为环境变量 `SANDBOX_PLATFORM_API_TOKEN`。当前演示环境使用配置文件中的演示 token；不得将它写入正式业务代码、截图或交付文档。

调用身份不再依赖自定义 HTTP 头传递，而以请求信封中的 `source` 和 `actor` 为准：

```text
source.layer = L2
source.service_code = 已登记业务引擎
actor.person_id = 当前责任真人
actor.tenant_id = 当前公司/租户范围
```

目前已登记可调用来源：

| `source.service_code` | 对应 L2 引擎 |
| --- | --- |
| `l2.workflow_execution` | 流程执行引擎 |
| `l2.rule_computation` | 规则计算引擎 |
| `l2.external_system_connector` | 外部系统对接引擎 |

## 4. 统一请求信封

`POST /api/v1/layer-interface/messages` 的请求体必须完整包含以下字段：

| 字段 | 必填 | 含义与本模块用途 |
| --- | --- | --- |
| `protocol_version` | 是 | 固定为 `1.0`。 |
| `message_id` | 是 | 本次 L2 -> L1 派发消息编号。 |
| `trace_id` | 是 | 贯穿 L4、L2、L1、回调和审计的追踪编号。 |
| `request_id` | 是 | L2 的派发单编号，不是沙箱内部任务编号。 |
| `parent_message_id` | 建议 | 上游命令或流程消息编号，用于还原父子关系。 |
| `source` | 是 | 必须是 `{layer:"L2", service_code:"..."}`。 |
| `target` | 是 | 固定 `{layer:"L1", service_code:"l1.execution_sandbox"}`。 |
| `channel` | 是 | 调用通道标识，例如 `l2_to_l1`。 |
| `route_type` | 是 | 固定为 `task.dispatch`。 |
| `action` | 是 | 必须与能力编号一一对应。 |
| `capability_id` | 是 | L2 从能力字典查得的沙箱能力编号。 |
| `capability_dictionary_version` | 是 | 本流程冻结的能力字典版本。 |
| `registry_version` | 是 | 本流程冻结的能力登记版本。 |
| `actor` | 是 | 当前真人：`person_id`、`tenant_id`。 |
| `context` | 是 | 必须包含 `workflow_instance_id`、`node_id`、`task_id`；数据应放 `data_refs/artifact_refs`，不默认复制正文。 |
| `idempotency_key` | 是 | 同一流程节点重试时必须保持不变，防止重复执行。 |
| `deadline_at` | 是 | ISO-8601 截止时间，例如 `2026-07-17T18:00:00+08:00`。 |
| `payload` | 是 | 本次能力的业务参数，见第 6 节。 |

## 5. 服务能力与动作匹配

调用方必须使用下表的正确组合；编号和动作不匹配会被拒绝。

| `capability_id` | `action` | 能力说明 |
| --- | --- | --- |
| `CAP.SANDBOX.TASK.RUN` | `sandbox.template.run` | 运行已登记岗位场景模板。 |
| `CAP.SANDBOX.CODE.RUN` | `sandbox.code.run` | 在默认断网 Docker 容器中运行 AI 生成的 Python 程序。 |
| `CAP.SANDBOX.BROWSER.RUN` | `sandbox.browser.run` | 在独立 Chromium 容器中打开白名单网页并采集结果。 |

三类能力的共同资源参数：

```json
"limits": {
  "timeout_seconds": 10,
  "memory_mb": 512,
  "cpu_cores": 1
}
```

限制范围：运行时长 `1-300` 秒，内存 `64-4096` MB，CPU `0.1-8` 核。`retain_snapshot=true` 时，任务结束保存包含运行时、日志和结果文件 SHA256 的不可变证据快照；不会保留可继续运行的容器。

## 6. 三类真实调用示例

以下示例省略重复的统一信封字段时，必须从第 4 节补齐，不能只发送 `payload`。

### 6.1 AI 临时代码隔离运行

用途：L2 已决定需要临时确定性计算或格式转换时，提交 AI 当场生成的 Python 程序。程序从 `/workspace/input.json` 读取输入，标准输出由接口返回。调用方不能提交 Shell、Docker 命令或自行指定网络策略。

```json
{
  "protocol_version": "1.0",
  "message_id": "msg-code-001",
  "trace_id": "trace-20260717-code-001",
  "request_id": "req-flow-code-001",
  "parent_message_id": "msg-command-001",
  "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
  "target": {"layer": "L1", "service_code": "l1.execution_sandbox"},
  "channel": "l2_to_l1",
  "route_type": "task.dispatch",
  "action": "sandbox.code.run",
  "capability_id": "CAP.SANDBOX.CODE.RUN",
  "capability_dictionary_version": "2026.07.17",
  "registry_version": "registry_2026.07.17",
  "actor": {"person_id": "demo-user", "tenant_id": "hanhe-group"},
  "context": {"workflow_instance_id": "flow-001", "node_id": "node-code-001", "task_id": "task-001", "data_refs": []},
  "idempotency_key": "flow-001-node-code-001-v1",
  "deadline_at": "2026-07-17T18:00:00+08:00",
  "payload": {
    "code": "import json\nvalues=json.load(open('/workspace/input.json'))['numbers']\nprint(sum(values))",
    "language": "python",
    "input": {"numbers": [7, 11, 13]},
    "limits": {"timeout_seconds": 10, "memory_mb": 128, "cpu_cores": 0.5},
    "retain_snapshot": true
  }
}
```

真实实现的安全边界：独立 Docker 容器、`network=none`、只读根文件系统、移除 Linux capabilities、禁止提权、进程数上限 64、资源上限和超时销毁。

### 6.2 浏览器白名单网页采集

用途：L2 已取得网页访问授权后，让浏览器在隔离容器内读取网页。`url` 必须是安全合规登记的白名单域名；当前测试白名单包括 `sandbox-allow.test`、`example.com` 等。

```json
{
  "protocol_version": "1.0",
  "message_id": "msg-browser-001",
  "trace_id": "trace-20260717-browser-001",
  "request_id": "req-flow-browser-001",
  "parent_message_id": "msg-command-002",
  "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
  "target": {"layer": "L1", "service_code": "l1.execution_sandbox"},
  "channel": "l2_to_l1",
  "route_type": "task.dispatch",
  "action": "sandbox.browser.run",
  "capability_id": "CAP.SANDBOX.BROWSER.RUN",
  "capability_dictionary_version": "2026.07.17",
  "registry_version": "registry_2026.07.17",
  "actor": {"person_id": "demo-user", "tenant_id": "hanhe-group"},
  "context": {"workflow_instance_id": "flow-001", "node_id": "node-browser-001", "task_id": "task-002", "data_refs": []},
  "idempotency_key": "flow-001-node-browser-001-v1",
  "deadline_at": "2026-07-17T18:00:00+08:00",
  "payload": {
    "url": "http://sandbox-allow.test",
    "input": {},
    "limits": {"timeout_seconds": 45, "memory_mb": 768, "cpu_cores": 1},
    "retain_snapshot": true
  }
}
```

本模块为每次请求创建内部 Docker 网络、专用 `egress-proxy`、Chromium 容器、结果目录和审计记录。浏览器只能经过代理访问；非白名单域名和直连绕过均被拦截。

### 6.3 已登记场景模板运行

用途：L2 需要运行本模块已登记的岗位场景验证模板。`scenario_id` 必须来自服务目录，例如 `s19_over_stock_warning`。

```json
"capability_id": "CAP.SANDBOX.TASK.RUN",
"action": "sandbox.template.run",
"payload": {
  "scenario_id": "s19_over_stock_warning",
  "agent": "supply-chain-agent",
  "input": {},
  "limits": {"timeout_seconds": 10, "memory_mb": 512, "cpu_cores": 1}
}
```

## 7. 标准回复与查询

### 7.1 已受理 `accepted`

长任务提交后通常立即返回 HTTP `202`：

```json
{
  "protocol_version": "1.0",
  "message_id": "msg-reply-001",
  "parent_message_id": "msg-code-001",
  "trace_id": "trace-20260717-code-001",
  "request_id": "req-xxxxxxxxxxxxxxxx",
  "source": {"layer": "L1", "service_code": "l1.execution_sandbox"},
  "target": {"layer": "L2", "service_code": "l2.workflow_execution"},
  "channel": "l2_to_l1",
  "route_type": "flow.callback",
  "reply_type": "accepted",
  "context": {"workflow_instance_id": "flow-001", "node_id": "node-code-001", "task_id": "task-001"},
  "data": {"task_id": "req-xxxxxxxxxxxxxxxx", "status": "accepted", "query": "/api/v1/layer-interface/messages/req-xxxxxxxxxxxxxxxx"}
}
```

L2 保存 `request_id`，随后查询：

```http
GET /api/v1/layer-interface/messages/req-xxxxxxxxxxxxxxxx
Authorization: Bearer <platform-token>
X-Caller-Layer: business_engine
X-Engine-Id: flow-execution-engine
X-Company-Id: hanhe-group
X-Trace-Id: trace-20260717-code-001
```

说明：提交时调用身份以标准信封 `source/actor` 为准；当前查询接口为保护已受理记录，仍要求带调用层、引擎、公司范围和追踪号。平台统一服务身份系统接入后，这些查询范围将由服务凭证和身份上下文替代。

### 7.2 成功 `success`

终态成功返回 `reply_type=success`。`data` 内含真实沙箱 `task_id`、业务结果、结果文件和耗时；`evidence` 内含执行器、Docker 运行时、资源配额、生命周期日志、审计和快照信息。

### 7.3 失败 `failed`

权限不足、参数非法、白名单拒绝、超时或执行错误均返回 `reply_type=failed`：

```json
{
  "reply_type": "failed",
  "error": {"code": "permission_denied", "message": "..."},
  "retryable": false
}
```

`retryable=true` 只表示运行失败或超时可由流程执行按同一 `idempotency_key` 处理；不表示可以绕过权限或安全拦截重试。

## 8. 稳定错误码

| 错误码 | HTTP | 含义 |
| --- | ---: | --- |
| `invalid_platform_token` | 401 | 服务调用凭证无效。 |
| `layer_route_not_allowed` | 403 | 不是 L2 -> L1 调用。 |
| `source_service_not_registered` | 403 | 来源 L2 服务未登记为沙箱调用方。 |
| `target_service_mismatch` | 400 | 目标不是 `l1.execution_sandbox`。 |
| `capability_not_registered` | 404 | 能力编号未登记。 |
| `capability_action_mismatch` | 400 | 能力编号与动作不匹配。 |
| `route_type_not_allowed` | 400 | 不是 `task.dispatch`。 |
| `invalid_deadline` | 400 | 截止时间不是 ISO-8601。 |
| `trace_id_conflict` | 409 | 同一幂等键对应不同请求内容。 |
| `permission_denied` | 200/终态 | 任务在 Docker 创建前被拒绝。 |
| `url_not_allowlisted` | 403 | 浏览器 URL 未经白名单允许。 |
| `invalid_limit` | 400 | CPU、内存或时长超出本模块限制。 |

## 9. 数据、文件与审计边界

- 业务数据和附件应传 `data_refs/artifact_refs`，不默认塞入 `payload` 原文。
- 结果文件当前作为沙箱临时产物返回；后续固定保存必须由数据操作引擎发起独立 `data.persist` 动作，不能把生成或采集结果自动当成长期存档。
- `retain_snapshot=true` 只保存运行证据快照和文件校验值，不保存容器，也不等同于业务数据归档。
- 外部网页连接必须走安全合规白名单；本模块记录目标、方法、允许/拒绝、状态和时间，不在日志中记录密钥正文。

## 10. 已验证实测记录

| 时间 | 正式能力 | 真实结果 |
| --- | --- | --- |
| 2026-07-17 | `CAP.SANDBOX.CODE.RUN` | Docker 执行 Python 输入 `[7,11,13]`，返回 `sum=31`，耗时 842ms，默认断网并生成快照。 |
| 2026-07-17 | `CAP.SANDBOX.BROWSER.RUN` | 动态创建内部网络、代理和 Chromium 容器，访问受控白名单页成功，耗时 3058ms；审计记录目标页 200，非白名单 Chromium 后台连接 403。 |
| 2026-07-17 | 标准消息入口 | 提交完整 v0.3 信封后返回 `accepted`，带父消息、流程上下文、查询路径。 |

## 11. 当前联调边界

本模块已真实实现标准信封、Docker 隔离、资源限制、浏览器白名单、结果和证据返回。以下内容已预留字段或适配位置，但必须等责任模块真实接入后才可宣称生产完成：

- L1.8 提供正式真人、岗位和租户事实。
- L1.1 提供每次动作的 `decision_id`。
- L1.9 提供安全义务、脱敏、正式白名单和不可篡改审计。
- L1.7 解析 `data_refs/artifact_refs`，保存正式产物和执行临时数据生命周期。
- L1.12 接收正式资源计量和成本记账。
