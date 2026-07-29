# L1-1.3 进化机制最小联调包

用途：让 1.2、1.4、1.7、数据、权限、审计等模块先用统一契约跑通框架逻辑。当前实现是本地模拟适配器，不代表正式生产数据库或正式网关。

## 已覆盖的核心链路

```text
业务引擎
  -> createCandidate
  -> riskCheck
  -> confirm（本人确认）
  -> approve（中风险/共享范围时）
  -> publish（写入 1.7）
  -> getAuditLog
  -> rollback
```

## 文件说明

| 文件 | 用途 |
|---|---|
| `contracts/evolution-contract.json` | 请求、响应、状态和错误码总契约 |
| `fixtures/success-low-risk.json` | 低风险成功发布样例 |
| `fixtures/blocked-missing-evidence.json` | 证据不足拦截样例 |
| `adapters/1.3联调适配器.js` | 把现有 1.3、风险判断和 1.7 模拟存储拼成可调用适配器 |
| `mock-services/联调模拟服务.js` | 本地 HTTP 联调入口 |
| `run-integration-tests.js` | 自动跑成功、拦截、权限、审计、回退测试 |

## 启动模拟服务

在本目录执行：

```powershell
node .\mock-services\联调模拟服务.js
```

默认地址：`http://127.0.0.1:8790`

## 联调请求顺序

1. `POST /api/l1/evolution/candidates`
2. `POST /api/l1/evolution/candidates/{candidateId}/risk-check`
3. `POST /api/l1/evolution/candidates/{candidateId}/confirmations`
4. 如返回 `pending_approval`，调用 `POST /api/l1/evolution/candidates/{candidateId}/approvals`
5. `POST /api/l1/evolution/candidates/{candidateId}/publish`
6. `GET /api/l1/evolution/audit`
7. 需要回退时调用 `POST /api/l1/evolution/assets/{agentId}/rollback`

## 联调约定

- 所有写请求携带 `requestId`、`actorId`、`tenantId`、`idempotencyKey`。
- `actorType` 默认必须为 `human`；本人确认时 `actorId === subjectUserId`。
- 证据不足返回 `need_more_evidence`，不得进入发布。
- 中风险需要 `BUSINESS_OWNER` 审批；高风险或专业审查场景保持阻断。
- 失败请求也写审计，不能只记录成功。
- 1.3 只负责机制、风险关卡和流程，不直接拥有业务资产的最终物理存储。
