# 第一版迁移说明

| 第一版 | 联调准备版 v1.0 |
|---|---|
| `POST /api/tasks` 自定义 JSON | `POST /api/v1/human-tasks` 统一请求信封 |
| `process_id` | `context.workflow_instance_id` |
| `node_id` | `context.node_id` |
| 本地 `task_id` 与上游任务混用 | `human_task_id` 与 `context.task_id` 分开 |
| `resume_payload` 保存完整续跑信息 | 删除；仅保存流程、节点、任务关联编号 |
| `auto_pass` | 删除；由规则计算/流程执行判断 |
| `takeover` | 删除 |
| `approve/modify_approve/reject/takeover` | 仅 `approve/modify_approve/reject` |
| `callback_to_1_2` | 标准 `flow.callback` 结果，仅供 L2 流程执行引擎认领 |
| 业务引擎可直接调用模块 | 正式调用必须经过 L1 层接口 |
| 1.11 自己描述流程继续/终止 | 1.11 只返回决定和最终结果，流程推进归 L2 |
| 自定义创建成功返回 | 统一 `accepted/success/failed` |

旧数据库不会被自动迁移。本联调版默认创建新的 `human_collaboration_v1.db`，避免旧状态字段干扰。
