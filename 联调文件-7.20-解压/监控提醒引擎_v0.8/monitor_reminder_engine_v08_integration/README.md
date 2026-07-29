# 监控提醒引擎 v0.8 联调精简包

## 1. 本包用途

本包用于平台框架联合联调，只保留监控提醒引擎后端核心代码、统一层内任务接口、Mock 适配器、配置、接口说明、联调准备表和最小联调测试客户端。


接口说明和联调准备表已直接放在项目根目录，与 `api_server.py` 同级，解压后即可看到。
本包不包含 Dashboard 图形界面、工作汇报、演示截图、历史测试报告、阶段性脚本、输出日志、`.venv`、`.idea`、`__pycache__`、`.pyc` 和历史数据库。

当前运行模式为 **Mock 独立功能验证**。正式 URL、认证方式、`service_code`、`capability_id`、平台状态枚举和真实基础模块接口需在联合联调时确认。

## 2. 核心职责与边界

- 监控事项登记、修改、启用、暂停、恢复、停用和查询；
- 提醒去重、同类合并、重复间隔、免打扰和紧急例外治理；
- 固定模板组装、按岗位解析接收人和通知送达；
- 提醒、送达、确认、升级和恢复销记五类记录只增不改；
- 通过 `trace_id` 查询全过程。

职责边界：不做阈值判定、不自建调度、运行期不调用大模型、同层执行引擎不直接互调。

## 3. 环境

- Python 3.9 或更高版本；
- 核心代码仅使用 Python 标准库，无需安装第三方依赖；
- 默认 API 地址：`http://127.0.0.1:8020`；
- 首次启动会自动创建本地 Mock 数据库 `monitor_demo.db`。

为避免 Windows 旧版 Python 的中文路径兼容问题，建议解压到纯英文目录，例如：

```text
C:\joint\monitor_v08
```

## 4. 启动 API

在 PowerShell 中进入解压后的项目目录：

```powershell
cd "C:\joint\monitor_v08"
python .\api_server.py
```

注意：本包没有 Dashboard 图形界面。启动成功后通过 API、健康检查或测试客户端验证。

健康检查：

```text
GET http://127.0.0.1:8020/api/v1/health
```

统一层内任务入口：

```text
POST http://127.0.0.1:8020/api/v1/l2/internal/messages
```

## 5. 联调测试

保持 API 服务运行，另开一个 PowerShell，在同一目录执行：

```powershell
python .\integration_test_client.py
```

测试覆盖来源准入、统一信封、监控事项登记、幂等重放、幂等冲突、提醒办理和全过程追踪。脚本中的部分 `400/409` 响应是预期的异常场景验证，不表示程序启动失败。

## 6. 目录说明

```text
api_server.py                    API 服务入口
integration_test_client.py       最小联调测试客户端
api/                             统一消息、能力路由与标准回复
adapters/                        数据、账号、权限、安全、通知、流程回调 Mock
repositories/                    数据访问与追踪仓储
config/                          能力、模板和治理规则配置
service_*.py                     核心业务服务
监控提醒引擎接口说明_v0.8_最终版.md                 详细接口契约
监控提醒引擎模块联调准备表_v0.8.docx  联调说明
```

## 7. 正式联调替换点

- `mock_data_module.py` → L1.7 数据模块；
- `mock_account_gateway.py` → L1.8 账号网关；
- `mock_permission_management.py` → L1.1 权限管理；
- `mock_security_compliance.py` → L1.9 安全合规；
- `mock_notification_channel.py` → 正式通知通道；
- `mock_workflow_callback.py` → 流程执行引擎正式回调。
