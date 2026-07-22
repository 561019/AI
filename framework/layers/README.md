# 三层模块目录

本目录是模块的固定归属入口；运行端口、标准接口和实现文件统一登记在各层的 `modules.py` 中。当前最小框架为了零依赖启动，HTTP Handler 仍集中在 `framework/server.py`，但模块之间只允许通过登记的 HTTP 接口通信，不允许跨模块函数调用。

- `business_application`：业务应用层，只能调用业务引擎层网关。
- `business_engine`：业务引擎层，包含意图、流程、规则以及引擎网关。
- `foundation`：基础模块层，包含权限、模型调度、能力注册以及基础层网关。

运行时调用情况请访问 `http://127.0.0.1:8100/monitor`。
