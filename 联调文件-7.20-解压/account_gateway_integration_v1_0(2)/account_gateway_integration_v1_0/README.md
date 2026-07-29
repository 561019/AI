# 汉和账号网关联调交付包

本交付包包含账号网关、独立权限服务、接口说明、数据库字典、账号-岗位-权限对应关系表、示例数据和联调检查表。

身份口径：账号创建时已经实名，真人就是账号。同一主体统一使用一个 ID：`user_id = actor_id = person_id`，不再维护账号到真人的二次映射。

## 目录

```text
account_gateway_integration_v1_0/
├── account-gateway/          # Go 账号网关，默认 8080
├── permission-gateway/       # Python 权限服务，默认 8001
├── handoff/                  # 联调说明和 CSV 表
└── 联调检查表.md
```

## 最快启动

1. 安装 Docker Desktop，并确认 Docker Compose 可用。
2. 进入 `account-gateway/`。
3. 复制 `.env.example` 为本地 `.env`，仅在本机修改配置，不要把真实密钥回传。
4. 执行 `docker compose up --build`。
5. 检查：
   - 账号网关：`GET http://127.0.0.1:8080/health`
   - 权限服务：`GET http://127.0.0.1:8001/health`

默认 `PERMISSION_MODE=remote`。账号网关不再产生业务权限 allow/deny；权限服务异常时一律拒绝，不回退本地放行。

## 推荐阅读顺序

1. `账号网关模块联调准备表.txt`
2. `接口说明.md`
3. `网关模块边界与权限接口映射.md`
4. `账号岗位权限对应关系.md`
5. `tables/api_catalog.csv`、`tables/error_codes.csv`
6. `tables/database_dictionary.csv`、`tables/schema_relationships.csv`
7. `tables/gateway_module_boundaries.csv`、`tables/gateway_permission_field_mapping.csv`
8. `diagrams/` 下的流程图和时序图
9. `联调检查表.md`

两张时序图使用 draw.io UML 生命线格式，源文件可直接在 draw.io 中打开和继续编辑。

## 联调主入口

新系统优先只对接以下入口：

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/identity/context` | 签发短时实名账号身份上下文 |
| `POST` | `http://127.0.0.1:8002/api/layer/dispatch` | 已登记 L2 服务唯一的运行期业务入口 |
| `POST` | `http://127.0.0.1:8001/api/org/commands` | 权限模块控制面：岗位及授权相关组织引用 |
| `POST` | `http://127.0.0.1:8001/api/permissions/commands` | 权限模块控制面：岗位标准、转授、数据及资源发布 |
| `GET` | `http://127.0.0.1:8001/api/permission/audits` | 权限决策审计查询 |

`/auth/validate` 仅用于遗留调用方的 fail-closed 兼容，业务系统不得把它当作正式判权入口；`/api/permission/check` 仅接受 L1 对内通道的机制性直达请求。

完整接口见 `tables/api_catalog.csv`。
