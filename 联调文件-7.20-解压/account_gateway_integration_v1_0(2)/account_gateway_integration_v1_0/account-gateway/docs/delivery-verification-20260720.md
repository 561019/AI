# 交付验证记录 2026-07-20

本次按“账号网关完整交付、权限模块核心逻辑验证”复核。

| 项目 | 结果 |
|---|---|
| 账号网关 Go 核心包 | `auth`、`gateway`、`identity`、`layerapi`、`permissionclient` 通过 |
| Compose 配置与启动 | 通过；默认 `PERMISSION_MODE=remote`，账号网关、权限服务和 L1 层接口均健康 |
| 网关公开职责 | 身份、账号、租户和组织事实；迁出权限能力统一返回 HTTP 410 |
| Web 控制台 | 源码、静态资源、`package.json` 和 lockfile 纳入联合包；不含 `node_modules` |
| 权限模块核心测试 | `25 passed` |
| 层接口核心测试 | `3 passed` |
| 权限数据库迁移 | 空 SQLite `alembic upgrade head` 到 `0004_resource_publication_grants` |
| ZIP 安全扫描 | 无 `.env`、数据库、日志、缓存、虚拟环境或编译产物 |
| Docker 镜像构建 | 三项镜像构建通过；账号网关在 Docker 内使用 `CGO_ENABLED=1` |
| 全量账号网关 E2E | **通过：107 passed**。旧 UI、审批、资源与转授场景已改为 `410 permission_capability_moved` 迁移契约；等价的运行期授权均走 `L2 -> L1 层接口 -> 权限模块 -> 登记目标服务`。 |

本机宿主环境缺少 GCC 且 `CGO_ENABLED=0`，无法直接运行依赖 `go-sqlite3` 的完整网关 Go 套件；正式 Dockerfile 安装 `build-base` 并使用 `CGO_ENABLED=1`。
