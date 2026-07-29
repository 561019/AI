# 项目管理引擎 v0.6 联调精简包

## 1. 本包用途

本包用于平台框架联合联调，只保留项目管理引擎后端核心代码、统一层内消息接口、Mock 适配器、配置、接口说明、联调准备表和最小联调测试客户端。

接口说明和联调准备表已直接放在项目根目录，与 `api_server.py` 同级，解压后即可看到。

本包不包含 Dashboard 图形界面、工作汇报、演示截图、历史阶段文档、输出日志、`.venv`、`.idea`、`__pycache__`、`.pyc` 和历史数据库。

当前运行模式为 **Mock 独立功能验证**。正式 URL、认证方式、`service_code`、`capability_id`、平台状态枚举及真实基础模块接口需在联合联调时确认。

## 2. 核心职责与边界

- 普通项目、重大项目登记及审批结果登记；
- 项目状态和项目档位维护；
- 项目成员加入、变更、退出和名册查询；
- 项目收尾、批量收权和归档封存；
- 封存项目重新授权与事后查询；
- 异步任务、进度、最终回调和状态查询；
- 通过项目编号和 `trace_id` 查询全过程。

职责边界：不组织审批流程、不直接授予或收回权限、不直接承担物理数据存储、不自建项目分析能力。

## 3. 环境

- Python 3.9 或更高版本；
- 依赖：FastAPI、Uvicorn、Pydantic；
- 默认 API 地址：`http://127.0.0.1:8008`；
- 首次启动会自动创建本地 Mock 数据库 `project_management.db`。

为避免 Windows 中文路径兼容问题，建议解压到纯英文目录，例如：

```text
C:\joint\project_v06
```

## 4. 安装与启动

在 PowerShell 中进入解压后的项目目录：

```powershell
cd "C:\joint\project_v06\project_management_engine_v06_integration"
pip install -r .\requirements.txt
python .\api_server.py
```

注意：本包没有 Dashboard 图形界面。启动成功后通过 API、Swagger 或测试客户端验证。

健康检查：

```text
GET http://127.0.0.1:8008/health
```

Swagger：

```text
http://127.0.0.1:8008/docs
```

统一层内消息入口：

```text
POST http://127.0.0.1:8008/api/v1/l2/internal/messages
```

## 5. 联调测试

保持 API 服务运行，另开一个 PowerShell，在同一目录执行：

```powershell
python .\integration_test_client.py
```

测试覆盖健康检查、普通项目登记、成员加入、统一消息查询、重复消息拦截和全过程证据查询。

脚本中的 `409 DUPLICATE_MESSAGE_ID` 是预期异常场景，不表示程序启动失败。

## 6. 目录说明

```text
api_server.py                         API 服务入口
integration_test_client.py            最小联调测试客户端
core/                                 统一消息、能力路由、准入、幂等与标准回复
adapters/                             账号、权限、安全、数据和归档 Mock
domain/                               项目模型、规则和状态机
services/                             项目登记、名册、档位、收尾、授权和查询服务
config/                               能力、来源路由、状态与 Mock 配置
项目管理引擎接口说明_v0.6_最终版.md        详细接口契约
项目管理引擎模块联调准备表_v0.6.docx       联调准备说明
```

## 7. 正式联调替换点

- `mock_account_gateway.py` → L1.8 账号网关；
- `mock_permission_management.py` → L1.1 权限管理；
- `mock_security_compliance.py` → L1.9 安全合规；
- `mock_workflow_callback.py` → 流程执行引擎正式回调；
- `mock_data_operation.py` → L2 数据操作引擎；
- `mock_project_repository.py`、`mock_archive_service.py` → L1.7 数据与归档服务。

## 8. 当前验证口径

当前版本已完成本地 Mock 独立功能验证和 API 联调准备，不代表真实平台模块已经接入，也不代表正式联合验收或生产上线。
