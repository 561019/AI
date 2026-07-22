# 异步任务与回调协议

## 状态机

```text
accepted → running → waiting_dependency → running
                   → waiting_human → running → succeeded
                   ↘ failed
accepted/running/waiting_dependency/waiting_human → cancelled
```

终态为 `succeeded`、`failed`、`cancelled`。终态不可回退。

## 受理回复

HTTP `202` 返回 `status=accepted`、`task_id`、`status_url` 和可选 `estimated_completion_at`。

## 回调事件

事件类型：

- `task.accepted`
- `task.started`
- `task.progressed`
- `task.waiting_dependency`
- `task.waiting_human`
- `task.succeeded`
- `task.failed`
- `task.cancelled`

回调必须携带原始 `trace_id`、`request_id`、`task_id`，并使用新的 `message_id`。同一任务的事件携带单调递增的 `sequence`；接收方按 `event_id` 幂等消费，并拒绝用旧事件覆盖新状态。

## 回调安全

- `callback_url` 只能使用能力登记或环境配置中的白名单地址，不能任意回调客户端传入地址。
- 回调使用服务身份认证，并包含时间戳与签名。
- 投递失败采用指数退避；默认最多 6 次。
- 达到重试上限后记录 `CALLBACK_DELIVERY_FAILED`，任务结果仍保留供状态接口查询。
- `waiting_dependency` 表示等待其他模块或外部系统，不能冒充 `running`；依赖返回后凭原 `trace_id` 和恢复令牌继续。

## 真人确认

进入 `waiting_human` 时创建 `confirmation_ref`，包含确认人范围、动作、对象摘要、过期时间和内容版本。提交确认时重新验证真人身份、权限、对象版本及任务状态；前端确认不能替代服务端校验。
