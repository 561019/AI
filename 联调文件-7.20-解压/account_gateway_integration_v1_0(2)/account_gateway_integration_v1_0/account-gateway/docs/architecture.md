# 架构定位

## 所在层级

`account-gateway` 在四层架构中的位置如下：

| 层级 | 位置 | 职责 |
|---|---|---|
| L1 基础模块层 | 1.8 账号网关 | 运行期账号与授权校验边界 |

该网关是 L1 基础设施模块，为上层提供共享的运行期决策点。它不负责产品工作流、UI 决策或长期业务流程状态。

## L1 职责

作为 L1 基础模块层 1.8，`account-gateway` 负责：

- 接收运行期校验请求。
- 在 `internal/gateway/validate.go:38-45` 校验 bearer JWT 是否存在、签名是否正确、是否过期。
- 在 `internal/gateway/validate.go:75-90` 从请求头读取授权上下文。
- 在 `internal/gateway/validate.go:58` 调用 `policy.Enforcer.Enforce`。
- 在 `internal/policy/model.conf:14` 应用策略模型。
- 在 `internal/gateway/validate.go:38-65` 返回最小化的允许或拒绝决策。
- 在 `internal/audit/writer.go` 写入 `/auth/validate` 调用审计记录。
- 在 `internal/account/lifecycle.go` 提供账号创建、读取、更新、删除的薄网关能力。

## 与 L2 的边界

当 L2 需要运行期授权决策时调用网关。

L2 提供：

- `Authorization: Bearer <jwt>`
- `X-User-ID`
- `X-Resource-Type`
- `X-Resource-Owner-ID`
- `X-Action`

L2 不应依赖内部策略 matcher 细节。它的稳定契约是 validate 响应：

- 允许决策：`{ "allow": true, "policy_id": "string" }`
- 拒绝或失败决策：`{ "allow": false, "policy_id": "string" }` 或 `{ "allow": false, "reason": "string" }`

L2 仍然负责自身领域工作流。网关只回答当前运行期动作是否允许。

## 与 L4 的边界

L4 将授权结果作为平台级或应用级护栏使用。

L4 可以使用网关决策来：

- 放行或阻断面向用户的操作；
- 将 `policy_id` 附加到日志或审计轨迹；
- 阻止缺少审批的数据动作。

L4 不应通过复制 `internal/policy/model.conf` 中的 matcher 来绕过网关。稳定边界是基于请求头的 validate 接口与 JSON 响应。

## v1 范围外

v1 中，网关不提供以下 L2 或 L4 功能：

- 用户体验流程；
- 审批工作流编排；
- 策略编辑 UI；
- 资源目录归属；
- 按记录查询数据；
- 完整生产级审计平台。
