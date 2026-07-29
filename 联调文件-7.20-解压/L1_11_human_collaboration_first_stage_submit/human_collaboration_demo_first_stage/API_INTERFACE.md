# L1.11 人机协同接口说明 v1.0

> 本文为联调准备稿。`capability_id`、能力字典版本和登记版本的最终值，以架构组正式能力登记为准。

## 一、服务边界

服务编码：`l1.human_collaboration`

本模块只处理人工待办本身，不保存完整流程实例。调用方应由 L2 流程执行引擎经 L1 层接口发起，并在完整流程状态库中保存原流程上下文。

正式人工决定只有：

```text
approve          同意
modify_approve   修改后同意
reject           驳回
```

不提供 `takeover`，不接收 `auto_pass`，不接收完整 `resume_payload`。

## 二、登记人工待办

### 请求

```http
POST /api/v1/human-tasks
Content-Type: application/json
```

请求必须使用统一信封，核心字段如下：

| 字段 | 说明 |
|---|---|
| `message_id` | 本次消息编号 |
| `trace_id` | 贯穿请求、待办、决定、结果和审计的追踪编号 |
| `request_id` | 本次请求编号 |
| `source.layer` | 必须为 `L2` |
| `source.service_code` | 通常为 `l2.workflow_execution` |
| `target` | 必须为 `L1/l1.human_collaboration` |
| `action` | 必须为 `human.task.create` |
| `actor` | 原业务责任真人及租户信息 |
| `context.workflow_instance_id` | 流程实例编号，仅保存关联编号 |
| `context.node_id` | 当前人工节点编号 |
| `context.task_id` | L2 上游任务编号 |
| `context.data_refs` | 相关数据引用，不默认传整份业务数据 |
| `context.artifact_refs` | 文件/产物引用 |
| `idempotency_key` | 防止重复创建 |
| `payload.target_person_id` | 待办处理人；正式权限由层接口/权限模块判定 |
| `payload.trigger_source_module` | 最初识别出人工需求的业务引擎，仅作来源说明 |

### 成功回复

HTTP `202`，`reply_type=accepted`：

```json
{
  "protocol_version": "1.0",
  "reply_type": "accepted",
  "trace_id": "trace_demo_001",
  "data": {
    "human_task_id": "HT-XXXXXXXXXX",
    "status": "pending",
    "target_person_id": "finance_checker_001",
    "deadline_at": "2026-07-20 10:00:00"
  }
}
```

相同 `idempotency_key` 再次提交时，不重复创建，返回原 `human_task_id` 并标记 `duplicate=true`。

### 主要失败情况

| 错误码 | 含义 |
|---|---|
| `SOURCE_LAYER_NOT_ALLOWED` | 请求不是来自 L2 层 |
| `TARGET_SERVICE_MISMATCH` | 目标服务不是 L1.11 |
| `DECISION_OPTIONS_INVALID` | 正式处理选项不是固定三种 |
| `422` 校验错误 | 信封字段缺失、类型不合法或包含已禁止字段 |

## 三、提交真人决定

### 请求

```http
POST /api/v1/human-tasks/{human_task_id}/responses
Content-Type: application/json
```

请求仍使用统一信封：

- `trace_id` 必须与原待办一致；
- `workflow_instance_id`、`node_id` 必须与原待办一致；
- `actor.person_id` 为实际处理人；
- `payload.decision` 只能是三种正式决定；
- `modify_approve` 必须提供非空 `modified_result`。

### 返回

```json
{
  "reply_type": "success",
  "data": {
    "message": "人工处理结果已登记，完整流程恢复由 L2 流程执行引擎完成。",
    "result": {
      "action": "flow.callback",
      "trace_id": "trace_demo_001",
      "workflow_instance_id": "flow_001",
      "node_id": "node_human_001",
      "task_id": "task_001",
      "human_task_id": "HT-XXXXXXXXXX",
      "human_task_status": "approved",
      "decision": "approve",
      "final_result": "上游结果或人工修正结果",
      "operator_id": "finance_checker_001",
      "comment": "已核对，同意。",
      "handled_at": "2026-07-19 20:00:00"
    }
  }
}
```

该结果只用于 L2 流程执行引擎认领；L1.11 不直接修改流程状态。

### 主要失败情况

| 错误码 | 含义 |
|---|---|
| `HUMAN_TASK_NOT_FOUND` | 待办不存在 |
| `TRACE_ID_MISMATCH` | 追踪编号不一致，不能认领 |
| `WORKFLOW_INSTANCE_MISMATCH` | 流程实例不一致 |
| `NODE_ID_MISMATCH` | 节点编号不一致 |
| `MODIFIED_RESULT_REQUIRED` | 修改后同意没有人工修正结果 |
| `HUMAN_TASK_ALREADY_FINISHED` | 已结束任务重复处理 |

## 四、催办与升级

催办：

```http
POST /api/v1/human-tasks/{human_task_id}/reminders
```

请求：

```json
{
  "operator_id": "system_reminder",
  "comment": "待办尚未处理，执行一次催办。"
}
```

升级：

```http
POST /api/v1/human-tasks/{human_task_id}/escalations
```

请求：

```json
{
  "operator_id": "system_timer",
  "escalate_to_person_id": "direct_leader_001",
  "comment": "按既定超时规则升级。"
}
```

当前版本只登记催办/升级结果。正式定时策略、处理人计算及权限判断以流程、权限和接口组最终方案为准。

## 五、状态定义

| 状态 | 含义 |
|---|---|
| `pending` | 待人工处理 |
| `escalated` | 已升级但仍待人工处理 |
| `approved` | 已同意 |
| `modified` | 已修改后同意 |
| `rejected` | 已驳回 |

没有 `taken_over` 和 `auto_passed`。
