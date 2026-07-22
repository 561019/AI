# 业务引擎接入指南

## 标准打包结构

每个业务引擎使用“平台适配器 + 原交付引擎服务”两段式结构：

```text
framework/layers/business_engine/<engine>/
  service.py                    # 平台标准字段与标准信封
  delivered_engine/service.py   # 原交付模块的真实核心入口
```

业务模块和流程执行引擎只调用平台适配器。适配器与原引擎之间也必须使用 HTTP，不允许跨模块直接调用函数。

## 接入步骤

1. 为引擎确定平台能力编号，例如 `content.generate`。
2. 在 `framework/core.py` 的能力表登记适配器 endpoint，不登记原引擎内部端口。
3. 原引擎包装服务复用交付代码中的核心类、校验器、提示词或执行器，并在响应中返回 `engine_meta.source=user-delivered-module` 和核心组件名称。
4. `service.py` 完成“平台标准字段 → 原字段 → 平台标准结果”的映射。
5. 在 `run_services.py`、`server.py`、`start_all.ps1`、`http.py` 和 `modules.py` 登记两个服务。
6. 外部依赖统一通过基础层接口调用：模型走 8300/8002，权限走 8300/8001；不得在业务引擎中直接读取 API Key。
7. 加入健康检查、字段映射测试、真实接口 live 测试和 Trace 调用链断言。

## 当前正式入口

| 引擎 | 平台适配器 | 原引擎内部接口 | 复用核心 |
|---|---|---|---|
| 意图分析 | 8000 | 8003 | `LLMTaskAnalyzer` |
| 流程执行 | 8020 | 8021 | `ModuleRegistry` |
| 规则计算 | 8010 | 8012 | `DeclarativeRuleExecutor` |
| 内容产出 | 8011 | 8013 | `adapt_content_subtask` + DeepSeek |

L1.2 模板管理已作为 8004 独立服务运行，L2 的 8021 `FlowExecutionEngine` 不直接调用模板代码，只能经 `8300` L1 层接口访问。当前模板仓库用于本地联调；流程实例使用 `framework/data/workflow_instances.json` 持久化。
