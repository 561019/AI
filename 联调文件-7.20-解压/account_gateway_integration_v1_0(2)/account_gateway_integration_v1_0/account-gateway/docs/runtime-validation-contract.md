# 运行期校验契约

## 范围

本文定义 `account-gateway` 的运行期校验契约。v2 后续完善已在保持旧请求兼容的前提下，增加真实资源 ID、租户头、岗位/真人上下文和枚举校验。

运行期校验由 `internal/gateway/validate.go` 中的 validate 接口实现。该接口把请求头转换为授权请求，然后调用 `policy.Enforcer.Enforce`。

实现锚点：

- JWT 校验：`internal/gateway/validate.go:42`
- 请求头解析：`internal/gateway/validate.go:75-90`
- Enforce 调用：`internal/gateway/validate.go:58`
- 响应结构：`internal/gateway/validate.go:20-24`、`internal/gateway/validate.go:38-65`
- 策略 matcher：`internal/policy/model.conf:14`
- 审计写入：`internal/gateway/validate.go:33-39`、`internal/audit/writer.go`

## 请求头

validate 接口从 HTTP 请求头读取授权上下文。

| 请求头 | 类型 | 必填 | 值域 | 运行期映射 |
|---|---:|---:|---|---|
| `Authorization` | string | 是 | `Bearer <jwt>`，JWT 需签名有效且未过期 | 由 `JWTManager.ValidateBearer` 校验 |
| `X-User-ID` | string | 是 | 非空用户身份字符串 | `validateRequest.sub`，作为 `r.sub` 传入 |
| `X-Resource-Type` | string | 是 | `tool`、`data`、`skill`、`knowledge`、`digital_employee` | `validateRequest.typ`，作为 `r.typ` 传入 |
| `X-Resource-ID` | string | 否 | 真实资源实例 ID；为空时回退到占位对象 | `validateRequest.obj`，作为 `r.obj` 传入 |
| `X-Resource-Owner-ID` | string | 是 | 资源所有者的非空用户身份字符串 | `validateRequest.owner`，作为 `r.owner` 传入 |
| `X-Action` | string | 是 | 非 data 资源使用固定动作枚举；data 资源优先查 `data_actions` 动作清单 | `validateRequest.act`，作为 `r.act` 传入 |
| `X-Tenant-ID` | string | 否 | 租户 ID；普通用户和普通 `hanhe_admin` 都必须与 JWT `org_id` 一致，只有 active breakglass 可越过该预检查 | 租户隔离预检查 |
| `X-Person-ID` | string | 否 | 真人编号；提供后启用组织岗位校验 | 与 active 挂岗记录中的 `person_id` 匹配 |
| `X-Position-ID` | string | 否 | 岗位席位 ID | 提供时必须匹配当前真人某个 active 挂岗岗位；不提供时可在该真人全部 active 岗位中匹配 |
| `X-Domain-ID` | string | 否 | 域 ID | 必须是已存在的域 |
| `X-Delegation-ID` | string | 否 | 个性化转授 ID | 指定后只允许该转授链路命中 |
| `X-Resource-Owner-Person-ID` | string | 否 | 资源归属真人编号 | 用于组织上下级权限判断 |

JWT 缺失、格式错误、签名错误或过期会返回 `reason: "invalid_token"`。其他必填请求头缺失或为空时，会返回 `reason: "missing_header"`。资源类型或动作不在允许范围内时失败关闭。对 `data` 资源而言，允许范围来自 `data_actions` 动作清单；对非 data 资源而言，仍使用固定动作枚举。

## 组织岗位口径补充

对照《岗位架构与权限授权机制说明 v1.7.1》，运行期校验主体必须是具体真人，而不是空岗位、流程实例或工具本身。岗位只携带标准配置；当真人担任岗位时，该标准配置才在真人身上生效。

当前 v2 契约中：

- `X-User-ID` 代表当前操作真人或可追溯到真人的数字员工身份。
- 数字员工 token 中的 `parent_user_id` 代表责任归属真人。
- `X-Resource-Owner-ID` 只表达资源 owner，不等同于人员唯一上级或管理域。
- `X-Tenant-ID` 只表达租户预检查，不等同于 Word 文档中的“域”。

当前 MVP 已增加 `X-Person-ID`、`X-Position-ID`、`X-Domain-ID`、`X-Delegation-ID` 和 `X-Resource-Owner-Person-ID`。不传 `X-Person-ID` 时保持旧的 Casbin 决策；传入后先检查 active 真人挂岗，再按数据登记初始权限、岗位标准资源、个性化转授链路、管理域下属树或资源目录层级放行。数据登记 owner 命中返回 `policy_id="data_owner:<data_id>:<action>"`；数据登记初始参与人命中返回 `policy_id="data_initial:<data_id>:<person_id>:<action>"`；岗位标准资源命中返回 `policy_id="position_standard:<id>"`；转授命中返回 `policy_id="delegation:<id>"`；管理域下属树命中返回 `policy_id="manager_scope:<domain_id>:<manager_person_id>:<owner_person_id>"`；资源目录命中返回 `policy_id="resource_scope:<resource_id>:<level>"`。

同一真人可以同时担任多个 active 岗位。传入 `X-Position-ID` 时，validate 只按该岗位上下文校验；未传 `X-Position-ID` 时，validate 会遍历该真人全部 active 岗位，岗位标准资源和资源目录层级可叠加命中。同一岗位席位同一时刻仍只允许一个 active 真人挂岗。

审批批准写入的 runtime policy 带 `tenant_id`。旧种子策略和旧兼容策略使用 `tenant="*"`，可作为全局基础策略；审批产生的 tenant-specific policy 只在请求 `X-Tenant-ID` 或 JWT `org_id` 匹配时生效，避免 A 租户审批影响 B 租户。

对照 v1.8.5 新增的“数据的产生、登记与授权”，当前已增加数据统一登记 MVP。对于已登记的 `data` 资源，运行期校验先执行数据自身约束，再执行人员权限判断：

- `X-Action` 未登记在 `data_actions` 或已禁用：接口级拒绝，HTTP 400，返回 `reason="invalid_action"`。
- `status != active`：直接拒绝，返回 `reason="data_record_inactive"`。
- `X-Action` 不在该数据 `allowed_actions`：直接拒绝，返回 `reason="data_action_forbidden"`。
- 当前 active person / user 与数据登记 owner 匹配，且动作属于创建者默认读/写类动作 `create/read/fetch/use/store/update`：直接放行，返回 `policy_id="data_owner:<data_id>:<action>"`。
- 当前 active person / user 命中数据登记的 `initial_person_ids` 或 `initial_user_ids`，且动作属于初始参与人读/取/使用类动作 `read/fetch/use`：直接放行，返回 `policy_id="data_initial:<data_id>:<person_id>:<action>"`。
- 数据未登记时保持旧兼容路径，继续按岗位标准资源、转授或管理域判断。

默认动作清单已种子化：`create`、`read`、`fetch`、`use`、`store`、`update`、`delete`、`approve`、`delegate`、`export`、`disable`、`freeze`、`unfreeze`。DSM/admin 可通过聚合命令 `register_data_action` 登记或重新启用动作；`register_data` 的 `allowed_actions` 必须来自该清单。

组织上下级权限当前只对 `data` 的 `read` / `fetch` 生效：当前真人必须是资源归属真人在 `X-Domain-ID` 内的直接或间接上级。若请求提供 `X-Resource-Owner-Person-ID`，优先使用该值；若该头为空且 `X-Resource-ID` 已登记到 `data_records`，validate 会从数据登记中推导 `owner_person_id`。该规则只表达“域内向下可见”的最小运行期校验，不替代数据放行审批或个性化转授链路。

资源目录层级只作用于 `tool`、`skill`、`knowledge`、`digital_employee`，不携带数据权限；其中数字员工共享只代表该非人账号资产可被使用，不能绕过“数字员工不直接访问 data、运行期按真人校验数据权限”的底线：

| 资源层级 | 放行条件 |
|---|---|
| `personal_position` | 当前 active person、position、user 与资源 owner 一致 |
| `department_public` | 当前 active position 的部门与资源部门一致，且 tenant 一致 |
| `company_public` | 当前 active assignment 的 tenant 与资源 tenant 一致 |

## 聚合联调入口

聚合接口只负责配置和状态写入 / 查询，不替代运行期校验。对外联调建议使用以下 5 个入口：

1. `POST /api/org/commands`：写入岗位、挂岗、域和上级关系。
2. `GET /api/org/snapshot`：读取组织岗位快照；可用 `manager_person_id` + `domain_id` 查询递归下属树。
3. `POST /api/permissions/commands`：写入岗位标准资源、转授、资源目录、数据动作清单、数据登记和发布升层申请 / 批准。
4. `GET /api/permissions/snapshot`：读取权限、资源、数据动作清单、数据登记和当前权限名单快照，可按 `person_id`、`resource_id`、`action`、`owner_user_id` 追溯转授链路。
5. `POST /auth/validate`：每次业务访问前做运行期授权校验。

细粒度接口仍保留为兼容和调试入口。完整字段与错误码见 `docs/aggregated-integration-api.md`。

聚合快照和对应细查询默认按 JWT `org_id` 过滤；未传 `tenant_id` 时只返回当前租户。普通 token 显式查询其他租户返回 403 `tenant_mismatch`；active breakglass 是应急例外。

`/api/permissions/snapshot` 中的 `data_access_summary` 是面向验收和联调的只读当前权限名单汇总，来源包括 `owner`、`initial_participant`、`position_standard`、`delegation`。该字段不替代 `/auth/validate`，只是把运行期可命中的主要授权来源提前展开，便于审计、对账和人工验收。

## 资源对象映射

如果请求提供 `X-Resource-ID`，该值会直接作为传给策略执行的对象值。未提供时，`internal/gateway/validate.go` 会把资源类型映射为占位对象，以兼容旧调用和旧测试。

| 资源类型 | 传给 enforcer 的对象 |
|---|---|
| `tool` | `tool_resource_placeholder` |
| `data` | `data_record_placeholder` |

## 成功响应

授权决策完成后，接口返回 HTTP 200：

```json
{
  "allow": true,
  "policy_id": "string"
}
```

enforcer 返回拒绝决策时也使用同样结构：

```json
{
  "allow": false,
  "policy_id": "string"
}
```

当 `policy_id` 为空时会省略，因为结构体标签是 `omitempty`。

## 失败响应

接口级失败返回：

```json
{
  "allow": false,
  "reason": "string"
}
```

`internal/gateway/validate.go` 中已实现的 v1 失败原因：

| HTTP 状态码 | 原因 | 代码锚点 |
|---:|---|---|
| 401 | `invalid_token` | `internal/gateway/validate.go:42-46` |
| 400 | `missing_header` | `internal/gateway/validate.go:48-52` |
| 400 | `invalid_resource_type` | `X-Resource-Type` 不在支持范围内 |
| 400 | `invalid_action` | `X-Action` 不在支持范围内 |
| 200 | `tenant_mismatch` | 非 breakglass token 的 `X-Tenant-ID` 与 JWT `org_id` 不一致 |
| 200 | `digital_employee_token_revoked` | 数字员工已禁用或 token version 已轮换 |
| 200 | `person_context_invalid` | 真人、岗位、租户、域或转授上下文与当前 active 挂岗不一致 |
| 200 | `data_record_inactive` | 数据登记状态不是 `active` |
| 200 | `data_action_forbidden` | 数据自身不允许本次动作 |
| 500 | `enforce_error` | `internal/gateway/validate.go:58-62` |
| 500 | `organization_state_error` | 组织岗位模型查询失败 |

## 铁律到 Enforce 逻辑的映射

### 铁律 1

规则：数据动一下要事前批，工具自己造自己改不用批。

实现：

- 工具自创建与自更新快捷路径写在 `internal/policy/enforcer.go:34-38`：
  - `typ == "tool"`
  - `act == "create" || act == "update"`
  - `sub == owner`
- 同样的规则也表达在 `internal/policy/model.conf:14` 的第一段 matcher 中。
- 数据资源不会匹配该快捷路径，因为快捷路径要求 `typ == "tool"`。
- 数据授权落到 `internal/policy/model.conf:14` 的策略匹配：
  - 角色或主体匹配：`g(r.sub, p.sub) || r.sub == p.sub`
  - 对象匹配：`p.obj == "*" || r.obj == p.obj`
  - 类型匹配：`p.typ == "*" || r.typ == p.typ`
  - 动作匹配：`r.act == p.act`

运行期链路：

- 在 `internal/gateway/validate.go:75-90` 读取请求头。
- 在 `internal/gateway/validate.go:58` 发送 enforce 请求。
- 在 `internal/policy/enforcer.go` 与 `internal/policy/model.conf:14` 评估请求。

### 铁律 2

规则：工具随便分享，数据按真人校验。

实现：

- validate 接口不使用调用方本地状态授权。它从 `X-User-ID` 读取真实动作执行人，并作为 `r.sub` 传入。
- 它从 `X-Resource-Owner-ID` 读取资源所有者，并作为 `r.owner` 传入。
- 对数据资源而言，工具快捷路径不能匹配，因为 `typ` 必须是 `tool`。因此，数据决策依赖真实主体和策略记录。
- 基于请求头的身份与归属读取在 `internal/gateway/validate.go:75-90` 实现。
- 策略执行在 `internal/gateway/validate.go:58` 调用。

## 观测与性能开关

- `AUTH_VALIDATE_TIMING=1`：日志输出 total、JWT、请求解析、enforce、审计写入耗时。
- `AUDIT_MODE=sync`：默认同步审计。
- `AUDIT_MODE=async`：异步队列审计，用于性能对照。
- `AUDIT_MODE=off`：关闭审计写入，仅用于性能定位，不建议生产使用。
- `SQLITE_JOURNAL_MODE=wal`：显式启用 SQLite WAL，用于性能对照；默认关闭以保持 Docker bind mount 下宿主机测试读取稳定。

## 仍需生产化

以下内容是 v1 占位行为，不是最终产品行为：

1. 未传 `X-Resource-ID` 的旧调用仍会落到占位对象。
2. 租户隔离当前先在 validate 契约层生效，尚未覆盖所有业务接口。
3. 审批通过后的运行期策略已写入 `runtime_policies` 并在服务启动时恢复；拒绝、撤销和审批人边界仍属后续生产化。
4. `policy_id` 语义依赖当前 enforcer 决策输出；审批批准、validate 命中和审计记录已保持同一 `policy_id`。
5. IM/DSM、域、唯一直接上级、组织树递归可见、岗位标准配置、个性化数据转授链路、资源目录、数据登记和资源发布升层已有 MVP；账号冻结、资源/数据进入 `offboarding` 资产池、锁定字段和交接确认详情已有后端 MVP，授权不可撤销治理、真实资产平台映射和交接界面仍需生产化。
6. data 动作已从硬编码枚举推进到 `data_actions` 清单，默认覆盖外发、临时冻结、解冻、转授等高风险动作；四类审批流程和动作对应的业务执行器仍需生产化。
