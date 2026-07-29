# 自动化测试结果

执行日期：2026-07-15

## 独立权限模块

命令：`python -m pytest -q`

- 结果：21 passed
- 已覆盖：健康检查、允许、拒绝、字段级 422、业务非法 400、账号/真人 ID 不一致拒绝、服务关系拒绝、制度拒绝优先、权限过期、数据状态前置、数据转授、多岗位、唯一岗位席位、管理树环路、租户隔离、审计不可改删、数据库故障 503、fallback 留痕、全平台能力发现和预留异步事件拒绝。

## 账号网关相关包

命令：`go test ./internal/permissionclient ./internal/gateway ./internal/organization ./internal/audit ./internal/auditapi ./internal/policy`

- 结果：全部通过。
- 新增覆盖：权限服务契约客户端、JWT 管理代理、旧请求头映射、remote 允许返回、服务不可用默认拒绝且不回退本地。

## 环境说明

本机直接执行 `go test ./...` 时，既有 `internal/credentials` 测试需要启用 CGO 的 `go-sqlite3`，当前本机 Go 环境为 `CGO_ENABLED=0`，因此该包无法加载 SQLite 原生驱动。Dockerfile 的正式构建阶段已设置 `CGO_ENABLED=1` 并安装 `build-base`；本次变更涉及的 Go 包均已独立通过。

## 交付与运行验证

- `docker compose config --quiet`：通过。
- `docker compose build permission-gateway account-gateway`：两个镜像均构建成功，账号网关在容器内以 CGO 编译 SQLite 驱动。
- Alembic 从空库升级到 `0002_account_person_identity (head)`：通过。
- 历史导入验证：旧 `person_id` 与 `user_id` 不同时，挂岗、管理树和转授关系均归并到 `user_id`：通过。
- `permission_gateway_v1_0.zip`：独立解压后 21 项测试通过。
- 本地 HTTP 冒烟：`GET /health`、岗位/挂岗/岗位标准配置、允许、拒绝和按 trace 查询审计均通过。
