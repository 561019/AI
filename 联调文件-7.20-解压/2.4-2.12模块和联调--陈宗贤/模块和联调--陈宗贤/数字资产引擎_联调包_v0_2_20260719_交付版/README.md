# 数字资产引擎：联调准备包 v0.2

本仓库实现数字资产引擎的核心登记能力，管理三类资产：**Agent、Skill、Knowledge Base**。

它负责资产登记、标签检索、版本留痕、Skill 的技术证据登记、知识源处理状态登记；它不负责业务数据、文档解析、业务计算、权限决策或跨模块流程编排。

## 先读

- [联调必读_v0_2_20260719.md](联调必读_v0_2_20260719.md)：唯一正式联调契约；
- [验证记录_v0_2_20260719.md](验证记录_v0_2_20260719.md)：本地测试范围和限制；
- [联调包清单_v0_2_20260719.md](联调包清单_v0_2_20260719.md)：交付内容。

## 正式联调入口

```text
POST /api/flow/tasks
```

仅接受流程执行引擎从 `L2 / l2.workflow_execution` 经 `l2_internal` 派发到 `L2 / l2.digital_asset` 的完整任务信封。请勿把本地控制台的 `/api/assets/*` 或 `/api/console/*` 当成跨模块接口。

## 本地运行

```powershell
python server.py
```

浏览器打开 <http://127.0.0.1:8765>。

## 回归验证

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

当前基线为 44 项 Python/HTTP 回归测试与 `web/app.js` 语法检查。

## 真实边界

L1.3、L1.7、L1.8、L1.9、L1.13、文档表格解析引擎和流程执行引擎在本仓库中都是 Mock 适配。测试通过只代表本模块的接口逻辑已验证，不代表这些真实模块已完成集成。
