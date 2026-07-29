# 执行沙箱能力包交付说明

## 1. 本次交付目标

本模块交付的是 L1 1.14 执行沙箱能力包，不是完整业务平台。

当前交付口径：

```text
Docker 运行时的 L1 1.14 执行沙箱能力包
```

它解决的问题是：当 L2 或其他上层模块要执行 Agent 代码、浏览器自动化或业务脚本时，提供一个可隔离、可限制、可销毁、可审计、可收集结果的运行环境。

## 2. 面向岗位场景

推荐完整演示场景：

```text
销售/供应链：跨部门同时下单超库存预警
```

岗位：

```text
销售员 sales-user
```

业务数据：

- 库存：50 吨。
- 三个部门订单：30 + 30 + 30 = 90 吨。
- 预期结果：超库存 40 吨，输出 `warning`。

## 3. 输入与输出

输入示例：

```json
{
  "scenario_id": "s19_over_stock_warning",
  "actor": "sales-user",
  "agent": "hanhe-supply-chain-agent",
  "timeout_seconds": 10,
  "memory_mb": 512,
  "cpu_cores": 1,
  "input": {}
}
```

输出包括：

- 任务状态。
- 业务结果。
- 结果文件。
- 沙箱生命周期日志。
- 账号、权限、mock ERP/OA、成本和审计证据。
- Docker 执行器和资源限制信息。

## 4. 模块边界

本模块负责：

- 创建隔离执行环境。
- 执行场景模板、代码任务和浏览器任务。
- 限制 CPU、内存、运行时长、默认网络。
- 通过 egress-proxy 验证白名单出站。
- 通过 credential broker 验证短期句柄凭据注入。
- 收集结果、日志、成本和审计线索。

本模块不负责：

- 判断任务是否应该执行。
- 提供真实员工权限系统。
- 提供真实 ERP/OA/CRM/数据库接口。
- 提供正式密钥管理系统。
- 提供完整业务自动化流程。

这些职责分别属于 1.4、1.8、1.9、1.10、1.12 和 L2。

## 5. 当前已实现

- Web 小界面 Demo。
- 20 个汉和场景模板。
- DockerTemplateExecutor。
- 宿主机文件隔离验证。
- CPU、内存、超时限制。
- 默认禁止出站。
- egress-proxy 白名单验证。
- Headless Chromium 浏览器沙箱。
- credential broker / 短期句柄凭据注入。
- E2B-like Docker adapter。
- 汉和销售/供应链超库存岗位场景 E2E。
- 汉和财务发票核销岗位场景 E2E。
- 汉和采购计划分析岗位场景 E2E。
- 交付清单、接口说明、测试报告、联调准备表和证据包接口。
- 正式证据包导出、现场验证报告和小并发调用测试报告。

## 6. 如何证明有用

可通过以下方式复查：

```text
GET /api/readiness
GET /api/acceptance
GET /api/compliance
GET /api/delivery/package
POST /api/verification/run {"case_id":"hanhe_role_scenario_e2e"}
```

当前验收目标：

```text
passed: 12
partial: 0
failed: 0
blocked: 0
future: 1
```

`future: 1` 是 Cube Sandbox，作为未来更强隔离选项保留，不作为当前 Docker 能力包交付阻塞。

## 7. 交付材料

- `README.md`
- `docs/MODULE_SPEC.md`
- `docs/BOUNDARY_SPEC.md`
- `docs/API_SPEC.md`
- `docs/TEST_REPORT.md`
- `docs/PLAN_COMPLIANCE.md`
- `docs/INTEGRATION_PREP_TABLE.md`
- `docs/DELIVERY_EVIDENCE.md`
- `docs/ROADMAP.md`
- `docs/evidence/*`

## 8. 当前不足

- Docker 是容器隔离，共享宿主机内核，不等同于 Cube/KVM 微虚拟机。
- mock ERP/OA、mock 安全合规、mock 账号网关和 mock 成本管控不是生产服务。
- E2B-like adapter 是当前 Docker 运行时的会话适配，不是完整 E2B SDK 兼容。
- 20 个场景是验证模板，不是 20 个完整业务系统。
- 正式生产还需要真实平台模块和真实业务系统联调。
