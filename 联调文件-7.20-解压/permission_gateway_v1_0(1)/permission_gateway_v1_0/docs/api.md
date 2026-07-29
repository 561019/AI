# 接口说明

## `GET /health`

数据库可用时返回 HTTP 200 和 `status`、`service`、`version`、`database`、`timestamp`。数据库不可用时返回 HTTP 503，不返回连接串或口令。

## `POST /api/permission/check`

必填字段为 `trace_id`、`request_id`、`actor_id`、`action`、`source_service`、`target_service`、`data_label`、`data_state`。可选字段为 `tenant_id`、`person_id`、`position_id`、`resource_type`、`resource_id`、`domain_id`、`requested_at`。

`actor_id` 必须是 JWT/账号系统的实名账号 `user_id`。兼容字段 `person_id` 如提供，必须与 `actor_id` 完全相同；不允许调用方使用另一套真人编号，不一致返回 HTTP 400 `INVALID_REQUEST`。

- HTTP 200：判断完成，`result` 为 `allow` 或 `deny`。
- HTTP 400：业务字段非法，包含 `person_id != actor_id`。
- HTTP 422：缺字段或类型错误。
- HTTP 500：模块内部异常。
- HTTP 503：数据库等依赖不可用。

## `GET /api/permission/audits`

支持 `trace_id`、`request_id`、`actor_id`、`result`、`from_ts`、`to_ts`、`after_id` 和 `limit`。

## 平台模块接入

### `GET /api/integrations/capabilities`

返回版本化平台契约、身份规则、已启用和已预留的通道，以及 L1、L2、L4 模块的 `source_service` 标识。该接口不返回任何人员、资源、规则或权限结果，可在新模块接入前读取。

### `POST /api/integrations/events`

异步生命周期事件地址已预留。请求包络固定为 `event_id`、`event_type`、`occurred_at`、`source_service`、`tenant_id`，并可带 `actor_id`、资源定位和 `payload`。

第一阶段该接口校验包络后固定返回 HTTP 501、`INTEGRATION_EVENT_NOT_ENABLED`，不会写入权限数据库。启用前需要服务认证/mTLS、事件幂等、持久化、重放和审计治理。当前人员、资源、数据和规则事实统一经账号网关代理的聚合管理接口同步。

## 管理聚合接口

- `POST /api/org/commands`
- `GET /api/org/snapshot`
- `POST /api/permissions/commands`
- `GET /api/permissions/snapshot`

管理接口仅接受账号网关验证后设置的 `X-Actor-ID`、`X-Actor-Roles` 和 `X-Tenant-ID`，默认只监听本机地址。
