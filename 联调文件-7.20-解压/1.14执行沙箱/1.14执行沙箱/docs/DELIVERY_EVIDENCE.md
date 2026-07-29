# 交付证据报告

## 交付口径

本模块当前交付为：

```text
Docker 运行时的 L1 1.14 执行沙箱能力包
```

Cube Sandbox 不作为当前交付阻塞项，保留为未来更强隔离运行时。

## 证据目录

正式证据文件保存到：

```text
docs/evidence/
```

证据清单由接口返回：

```text
GET /api/delivery/evidence
GET /api/delivery/package
POST /api/delivery/export
GET /api/delivery/export.zip
```

## UI 截图证据

| 文件 | 证明内容 |
| --- | --- |
| `docs/evidence/ui-run-task.png` | 小界面 Demo 能提交沙箱任务，并展示 20 个汉和场景模板。 |
| `docs/evidence/ui-verification.png` | 验收演示页能展示 Docker 隔离、出站、浏览器、凭据和岗位场景验证项。 |
| `docs/evidence/ui-monitor.png` | 沙箱监控页能查看沙箱实例、状态、权限、成本、审计和结果文件线索。 |
| `docs/evidence/ui-tasks.png` | 执行记录页能复查输入、输出、运行限制、日志和平台链路证据。 |
| `docs/evidence/ui-policy.png` | 安全边界与合规页能展示研发方案覆盖情况和客观验收检查结果。 |

## API 快照证据

| 文件 | 证明内容 |
| --- | --- |
| `docs/evidence/api-acceptance.json` | `/api/acceptance` 的真实返回。 |
| `docs/evidence/api-compliance.json` | `/api/compliance` 的真实返回。 |
| `docs/evidence/api-delivery-checklist.json` | `/api/delivery/checklist` 的真实返回。 |
| `docs/evidence/api-role-scenario.json` | `/api/delivery/role-scenario` 的真实返回。 |

## 归档报告和导出包

全量现场验证报告保存到：

```text
docs/evidence/reports/
```

生成接口：

```text
POST /api/verification/report
POST /api/verification/concurrency-report
GET /api/verification/reports
```

其中 `POST /api/verification/concurrency-report` 用于生成小并发调用测试报告，证明后续 L2 平台可以小批量调用沙箱能力包。

正式证据包保存到：

```text
docs/evidence/delivery-package.zip
```

该 zip 包包含交付文档、截图、API 快照、验证报告和 `delivery-package.json`。

## 当前验收标准

当前 Docker 可实现范围内，验收目标是：

```text
passed: 12
partial: 0
failed: 0
blocked: 0
future: 1
```

`future: 1` 是 Cube Sandbox，属于未来增强，不代表当前 Docker 能力包未完成。

## 复查方式

1. 打开 Demo：`http://10.60.66.97:8765/`
2. 查看交付包页：`http://10.60.66.97:8765/#delivery`
3. 调用证据接口：`GET /api/delivery/package`
4. 对照 `docs/evidence/*` 中的截图和 JSON 快照。

## 仍需外部模块配合的部分

- 1.4 驾驭机制：正式 allow/deny、最大步数、人工审批策略。
- 1.5 大模型调度：统一模型代理和模型凭据。
- 1.8 账号网关：真实员工、岗位、部门、租户和权限。
- 1.9 安全合规：正式策略中心、审计策略和密钥管理。
- 1.10 设备与系统接口：真实 ERP/OA/CRM/数据库适配器。
- 1.12 成本管控：正式成本计量和看板。
