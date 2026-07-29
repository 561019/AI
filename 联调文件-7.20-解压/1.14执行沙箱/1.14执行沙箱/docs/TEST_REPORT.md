# 测试结果文档

## 当前运行环境

服务器项目路径：

```text
/home/nlp/刘卓/执行沙箱
```

当前运行时：

```text
DockerTemplateExecutor
Docker version 26.1.3
agent-sandbox-python:3.10-local
agent-sandbox-browser:chromium-local
```

Demo 地址：

```text
http://10.60.66.97:8765/
```

## 当前验收接口

```bash
GET /api/readiness
GET /api/acceptance
GET /api/verification
POST /api/verification/run
```

当前 `/api/acceptance` 结果：

```text
passed: 12
partial: 0
failed: 0
blocked: 0
future: 1
```

`future: 1` 为 Cube Sandbox，作为未来增强项保留，不作为当前 Docker 交付阻塞。

## 已验证能力

| 测试项 | 结果 | 说明 |
| --- | --- | --- |
| sandbox lifecycle | passed | 任务生命周期有 request/create/result/destroy 日志 |
| result collection | passed | 结果文件写入 `data/results` |
| real container isolation | passed | Docker 服务可用，任务由容器承载 |
| host file isolation | passed | 容器不能读未挂载宿主机文件，不能写只读 `/app` |
| resource timeout | passed | 跑飞容器被超时停止并清理 |
| egress allowlist | passed | 白名单域名通过，非白名单拒绝，直连绕过失败 |
| browser sandbox | passed | Headless Chromium 在只读 Docker 容器内运行；白名单加载受控页面，非白名单由代理日志 `allowed=false` 证明被拦截，直连只得到 ERR_/offline 错误页。Chromium 渲染错误页时 returncode 可能仍为 0，因此不以返回码单独判定 |
| credential injection | passed | 任务只拿凭据句柄，明文密钥不进入任务容器 |
| E2B-like adapter | passed | create/run/query/destroy 会话式调用链路可用 |
| Hanhe role scenario E2E | passed | 销售/供应链超库存预警端到端通过 |
| role permission matrix | passed | 同一 `sales-user` 在库存场景权限满足并进入 Docker，在发票场景缺少两项财务权限并于 Docker 创建前返回 `denied`，资源成本为 0 |
| Hanhe finance invoice E2E | passed | 财务发票核销端到端通过 |
| Hanhe purchase plan E2E | passed | 采购计划分析端到端通过 |

## 20 个场景模板状态

20 个汉和场景已注册并可执行。它们用于证明 L1 1.14 能接收任务、隔离执行、收集结果、展示证据。

注意：这些模板不是 20 个完整业务系统。短视频、OCR、真实发票验真、真实行情采集、质量检测、合同归档等业务能力需要其他模块和真实系统接口配合。

## 推荐完整岗位场景测试

推荐使用：

```text
跨部门同时下单超库存预警
```

测试输入：

```json
{
  "scenario_id": "s19_over_stock_warning",
  "actor": "sales-user",
  "agent": "demo-agent",
  "timeout_seconds": 10,
  "memory_mb": 512,
  "cpu_cores": 1,
  "input": {}
}
```

验证链路：

1. `sales-user` 通过 mock 账号网关解析为销售岗位。
2. mock 安全合规检查 `inventory:read` 和 `order:read` 权限。
3. mock ERP 注入库存 50 吨和 3 个部门合计 90 吨订单。
4. Docker 沙箱执行 `s19_over_stock_warning` 模板。
5. 输出超库存 40 吨预警。
6. 记录成本、审计、日志和结果。
7. UI 中可查看任务详情和链路证据。

## 已补充岗位场景

### 财务：发票核销

- actor：`demo-user`
- 场景：`s04_invoice_matching`
- 输入：由 mock ERP 注入发票和入库单。
- 输出：至少一张发票匹配、至少一张发票异常。
- 证明：财务岗位权限、ERP 数据注入、Docker 执行、结果收集、成本记录和审计留痕。

### 采购：采购计划分析

- actor：`demo-user`
- 场景：`s20_purchase_plan`
- 输入：由 mock ERP 注入历史采购数据和当前库存。
- 输出：预测需求、当前库存、建议采购量。
- 证明：采购/库存权限、ERP 数据注入、Docker 执行、结果收集、成本记录和审计留痕。

## 当前不足

- Docker 是容器隔离，强度不等同于 Cube/KVM 微虚拟机。
- Cube Sandbox 当前作为未来增强项，不作为本阶段交付阻塞。
- mock ERP/OA、mock 安全合规、mock 成本管控不是生产服务。
- 20 个场景是验证模板，不是每个场景的完整业务自动化。
- 正式联调需要 1.4、1.5、1.9、1.10、1.12 提供接口和测试环境。
