# 平台统一数据持久化

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
```

## 本地独立验证

无需启动服务即可运行：

```powershell
cd C:\Users\21964\Documents\联调
python framework\test_cases\validate_data_pipeline.py
```

该测试使用临时数据库，验证数据操作引擎持久化消息、账号创建和密码校验，不写入正式平台数据库。
