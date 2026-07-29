# L1 层接口判权准入

运行期 `POST /api/permission/check` 不再是业务模块接口。它只接受基础模块层对内通道的机制性直达请求：`ingress_mode=mechanism_direct`、`X-L1-Caller-Service=l1_internal_channel`，并通过 `X-L1-Mechanism-Secret` 校验调用身份。生产环境应将该本地开发密钥替换为 mTLS 客户端证书校验。

权限请求审计已增加责任真人、执行体、原始调用服务、入口模式、`transfer_id` 与身份上下文哈希。智能体只能作为 `executor_type=agent` 上下文，判权主体仍是 `responsible_actor_id` 对应真人账号。

机制直达请求还携带经层接口验签的 `identity_position_ids`。权限引擎用这些岗位事实匹配岗位标准规则，不在该正式路径查询 `persons` 或 `person_position_assignments`；两张表和旧组织查询仅在迁移兼容入口保留，后续将从权限库移除。

直接业务调用、伪造入口模式或错误通道身份返回 `403 UNTRUSTED_INGRESS`，且不会产生 allow/deny 决策。权限模块继续按实时数据库查询规则；不缓存判定结果。
