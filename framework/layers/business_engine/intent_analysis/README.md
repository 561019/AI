# 意图分析模块正式接入说明

本目录包含两个独立运行、只通过 HTTP 接口通信的组件：

- `service.py`：平台标准适配器，端口 `8000`，接口 `POST /api/v1/intent/analyze`。
- `delivered_engine/service.py`：用户交付意图引擎的正式运行入口，端口 `8003`，接口 `POST /api/v1/delivered-intent/analyze`。

正式调用链为：

`应用层 → 引擎网关 → 平台意图适配器(8000) → 原始意图引擎(8003) → 基础层网关(8300) → 大模型调度(8002) → DeepSeek API`

8003 服务直接复用交付模块中的 `LLMTaskAnalyzer`、原始提示词、`IntentAnalysisResult` 校验、证据校验和 `FunctionRegistryCatalog`。平台适配器只负责把原模块字段映射为平台标准字段，不代替原模块分析意图。

## 使用入口

业务使用和对话验证请进入：

- 对话案例：`http://127.0.0.1:8100/chat`
- 调用链监控：`http://127.0.0.1:8100/monitor`
- 全部接口文档：`http://127.0.0.1:8100/docs`

诊断原模块时可以直接查看：

- 原模块健康状态：`http://127.0.0.1:8003/health`
- 平台意图适配器健康状态：`http://127.0.0.1:8000/health`

业务系统不应绕过平台适配器直接调用 8003。8003 是层内接口，8000 是平台标准接口。
