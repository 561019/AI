# 数据库说明

核心事实表：`persons`、`departments`、`positions`、`person_position_assignments`、`domains`、`person_manager_edges`、`position_standard_permissions`、`data_delegations`、`institution_policies`、`service_call_rules`、`data_registry`、`data_actions`。

## 身份主键

`persons` 是实名账号档案镜像，不是独立人员主数据。账号创建时已经完成实名，数据库强制以下等式：

```text
persons.id = persons.actor_id = Casdoor/JWT user_id
assignment.person_id = assignment.actor_id
data_registry.owner_person_id = data_registry.owner_actor_id
resources.owner_person_id = resources.owner_actor_id
```

管理关系和转授关系中的 `person_id`、`manager_person_id`、`from_person_id`、`to_person_id` 也都引用 `persons.id`，即引用实名账号 ID。模型检查约束和 SQLite 触发器共同拒绝不一致写入。

`0002_account_person_identity` 会先把旧库中的挂岗、上下级、转授、数据 owner、资源 owner、初始参与人和历史决策引用从旧 `person_id` 归并到对应 `actor_id/user_id`，再安装写入触发器。升级前仍应备份 SQLite 文件；无法唯一归并的冲突数据会让迁移失败，不会静默保留双身份。

`permission_decisions` 是权限专用追加式审计表，数据库触发器禁止 UPDATE 和 DELETE。SQLite 数据默认位于 `data/permission.sqlite3`，初始化和升级使用 Alembic。

一个实名账号允许同时担任多个岗位；一个岗位席位同一时刻只能存在一个 active 任职。同一租户、域、账号只能存在一个 active 直属上级，服务层同时拒绝自关联和组织环路。

## 主要关系

| 主表 | 从表/字段 | 关系 | 含义 |
|---|---|---|---|
| `persons.id` | `person_position_assignments.person_id` | 1:N | 一个账号的当前及历史任职 |
| `positions.id` | `person_position_assignments.position_id` | 1:N（按时间） | 岗位席位任职历史 |
| `positions.id` | `position_standard_permissions.position_id` | 1:N | 岗位标准配置 |
| `persons.id` | `person_manager_edges.person_id` | N:1 active/domain | 账号在域内的唯一直属上级 |
| `persons.id` | `person_manager_edges.manager_person_id` | 1:N | 管理树向下范围 |
| `persons.id` | `data_delegations.from_person_id/to_person_id` | 1:N | 账号之间的数据转授 |
| `persons.id` | `data_registry.owner_person_id` | 1:N | 数据责任账号 |
| `permission_decisions.actor_id` | `persons.id` | N:1 | 决策追溯到实名账号 |
