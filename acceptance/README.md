# 框架验收测试工程

本工程验证平台接口契约、三层边界、权限、幂等、异步回调和端到端闭环。

## 模式

- `contract`：只验证本仓库契约文件和测试场景，现在即可运行。
- `live`：调用已经启动的真实框架服务；未提供配置时明确跳过。
- `all`：同时运行上述两类测试。

## 运行

使用工作区依赖中的 Python，或任意 Python 3.11+：

```powershell
python acceptance/run_acceptance.py --mode contract
python acceptance/run_acceptance.py --mode live --config acceptance/config.local.json
python acceptance/run_acceptance.py --mode all --config acceptance/config.local.json
```

每次运行会在 `acceptance/reports/` 生成 JSON 报告。该目录已由 `.gitignore` 忽略。

## 真实环境配置

复制 `config.example.json` 为 `config.local.json`，填入实际服务地址和专用测试身份。不要把令牌或密钥提交到 Git。

实时测试默认只执行无副作用或测试租户内的请求。测试账号、规则和数据均须是专用测试资源。

## 验收范围

| 分组 | 验证内容 |
|---|---|
| contract | 公共字段、三种回复、七状态模型、本地引用、operationId 唯一性 |
| health | 三层网关和四个模块健康检查 |
| boundary | 应用层跨层直调、未登记来源、基础模块业务请求必须被拒绝 |
| permission | allow、deny、身份伪造、权限服务不可用时默认拒绝 |
| idempotency | 同键同内容复用结果、同键不同内容冲突 |
| async | 受理回执、状态查询、重复回调、乱序回调 |
| e2e | 意图确认、流程执行、权限判定、规则计算、结果返回 |

## 退出码

- `0`：所有实际执行的测试通过；允许存在因未配置真实环境而产生的跳过。
- `1`：至少一项失败或异常。

正式验收时不接受 live 测试跳过，应在 CI 中额外检查报告的 `skipped` 数量为零。
