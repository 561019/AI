# 平台统一数据持久化

> 2026-07-22 联调增强：本文描述当前代码已实现能力。完整生产设计见
> `架构/平台模块存储与数据访问权限详细设计_v2_0_20260722.md`。

## 存储位置

- 统一数据库：`framework/data/foundation_data/platform_data.db`
- 上传对象：`framework/data/foundation_data/objects/uploads/`
- 上传索引：`framework/data/foundation_data/objects/uploads/upload_index.json`

旧的 `framework/data/platform.db` 和 `framework/uploads/` 不会自动删除，保留为历史数据备份。

## 层级调用

```text
前端 -> L4 应用网关 -> L2 数据操作引擎 -> L1 基础层网关 -> L1 数据基础模块
```

账号数据使用：

```text
前端 -> L4 应用网关 -> L2 流程执行引擎 -> L1 账号网关 -> L1 基础层网关 -> L1 数据基础模块
```

模块不允许直接从前端写 SQLite 文件。

## 已接通的数据集

| 数据集 | 内容 |
|---|---|
| `accounts` | 账户基本资料 |
| `account_credentials` | PBKDF2-SHA256 密码摘要与盐，不允许通过验收查询接口读取 |
| `account_role_bindings` | 账户角色绑定 |
| `account_sessions` | 登录会话记录，不允许通过验收查询接口读取 |
| `conversations` | 对话主记录 |
| `conversation_messages` | 用户消息、意图结果、执行结果和失败结果 |
| `uploaded_files` | 上传文件元数据和对象引用 |
| `storage_objects` | 物理对象 ID、对象键、大小、SHA-256、内容类型和扫描状态 |
| `task_snapshots` | 任务状态、人工确认和最终结果快照 |

任务中心、幂等记录、能力登记和接口调用链也保存在同一个统一数据库中。

## 数据模块接口

内部标准接口：

```text
POST http://127.0.0.1:8060/api/v1/foundation-data/instructions
```

能力：

- `foundation_data.write`
- `foundation_data.read`
- `foundation_data.query`
- `foundation_data.source.register`
- `foundation_data.catalog.list`
- `foundation_data.access.trace`

## 数据集目录与访问控制

受控数据目录定义在 `framework/data_catalog.py`。每个数据集登记责任模块、数据分类、
默认保留策略、允许读写模块、敏感标志、必填字段和 Schema 版本。初始化后目录进入
`dataset_catalog` 表。

L1 数据模块当前强制执行：

- 未登记数据集返回 `DATASET_NOT_REGISTERED`；
- `tenant_id` 必填，普通调用不能覆盖当前真人租户；
- 来源模块必须出现在数据集允许读写名单中；
- 真人上下文携带 `allowed_project_ids` 时，按项目范围过滤或拒绝；
- 新建记录校验必填字段；
- 更新可传 `expected_record_version` 执行乐观锁；
- 每次允许或拒绝写入 `data_access_decisions`；
- 接口调用日志中的密码、Token、API Key 等字段自动脱敏。

L2 `data.trace` 已映射到 `foundation_data.access.trace`，可以按 `trace_id` 查询数据访问决策。
L2 `data.catalog` 已映射到 `foundation_data.catalog.list`，应用层无需越层访问 L1。

业务模块通过 L2 数据操作引擎写数据时，数据操作引擎会把原始请求模块作为受控委托来源
传给 L1。L1 按数据目录校验真正的业务请求模块，而不是把所有写入都笼统记作
`data-operation`。

流程执行引擎现在会固定保存：

- `workflow_instances`：流程实例和最终状态；
- `workflow_node_instances`：权限节点、承办能力节点及执行状态；
- `workflow_events`：启动、完成等流程事件。

## 文件对象登记

当前上传仍使用本地开发目录，但每次上传同时写入：

- `storage_objects`：物理对象账；
- `uploaded_files`：文件业务登记，并通过 `object_id` 引用物理对象。

跨模块应传 `object_id`，不应依赖 `saved_path`。`saved_path` 只用于当前本地联调，迁移
MinIO/S3 后应停止跨模块使用。

应用层验收查询：

```text
GET http://127.0.0.1:8100/api/v1/data/records?dataset=accounts
GET http://127.0.0.1:8100/api/v1/data/records?dataset=conversations
GET http://127.0.0.1:8100/api/v1/data/records?dataset=conversation_messages
GET http://127.0.0.1:8100/api/v1/data/records?dataset=uploaded_files
GET http://127.0.0.1:8100/api/v1/data/records?dataset=task_snapshots
```

完整接口传输仍通过：

```text
GET http://127.0.0.1:8100/api/v1/traces/{trace_id}/calls
GET http://127.0.0.1:8100/api/v1/runtime/session/{trace_id}
GET http://127.0.0.1:8100/api/v1/data/catalog
GET http://127.0.0.1:8100/api/v1/traces/{trace_id}/data-access
```

`runtime/session` 会汇总任务状态、上传文件、接口调用、数据访问决策以及流程实例/节点/事件，
用于按同一个 `trace_id` 验证完整数据流转。

## 本地独立验证

无需启动服务即可运行：

```powershell
cd C:\Users\21964\Documents\联调
python framework\test_cases\validate_data_pipeline.py
python framework\test_cases\validate_data_security.py
```

两个测试均使用临时数据库，不写入正式平台数据库。除原有消息持久化、账号创建和密码
校验外，还验证数据集白名单、跨租户拒绝、项目范围拒绝、敏感数据拒绝、记录版本冲突和日志脱敏。
