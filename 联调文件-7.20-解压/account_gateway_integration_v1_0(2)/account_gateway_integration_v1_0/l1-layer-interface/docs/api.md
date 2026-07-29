# L1 层接口 API v1

`POST /api/layer/dispatch` 是基础模块层唯一业务入口。调用方必须是已登记 L2 服务，并以 `X-L1-Service-ID`、`X-L1-Service-Signature` 证明服务身份；签名内容为 `request_id:nonce:service_id` 的 HMAC-SHA256。请求体的 `caller_layer` 与 `caller_service_id` 仅用于交叉校验，不能替代签名身份。

所有请求使用 `LayerRequestEnvelope`：必须提供追踪三元组、L2 调用方、登记目标服务和命令、租户、执行体、责任真人（系统制度动作除外）、资源四要素、账号网关签发的 `identity_context_token`、时间和 nonce。层接口校验令牌的账号、租户和过期时间。未登记服务、调用方不在白名单、重复 `transfer_id`、身份上下文无效或缺少责任真人均拒绝，且不会触达目标模块。

通道在路由前向权限模块发送唯一一次 `ingress_mode=mechanism_direct` 请求；请求带有 `l1_internal_channel` 身份、原始 L2 调用方、`transfer_id` 和身份上下文哈希。权限异常、超时、非 allow 结果一律停止转交。响应包络固定为 `trace_id`、`request_id`、`transfer_id`、`status`、`result`、`error`、`permission_decision_id`、`completed_at`。

当前登记的服务仅为账号网关的 `account.identity_context.v1` 与 `account.authenticate.v1`。前者已经采用受层接口身份保护的标准处理器；未迁入标准处理器的服务保持 fail-closed，不会伪造成功响应。
