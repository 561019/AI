# 初始服务登记

| service_id | module_id | command | 允许调用 L2 | 资源类型 |
|---|---|---|---|---|
| `account.identity_context.v1` | `account_gateway` | `identity.context.read_self` | `content_generation`、`workflow_engine`、`login_engine` | `identity_context` |
| `account.authenticate.v1` | `account_gateway` | `identity.authenticate` | `login_engine` | `identity` |

登记数据仅保存契约和路由元数据，不保存账号、岗位、权限、凭证或业务数据。变更登记应在控制面审计后发布；运行面只能读取 active 版本。
