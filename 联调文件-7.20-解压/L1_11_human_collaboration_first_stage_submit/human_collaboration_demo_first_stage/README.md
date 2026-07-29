# L1.11 人机协同模块（联调准备版 v1.0）

本版本按最新职责边界和 2026-07-17 层间交互规范调整。

## 1. 当前职责

L1.11 只负责：

- 接收经 **L1 层接口**转交的人工协同任务；
- 生成人工待办并维护待办自身状态；
- 记录催办和按既定规则产生的升级结果；
- 接收真人的 **同意、修改后同意、驳回**；
- 返回人工待办状态与处理结果，供 L2 流程执行引擎凭 `trace_id` 等编号认领。

L1.11 不负责：

- 主动发现业务异常；
- 判断低风险是否自动通过；
- 保存完整流程实例和流程续跑上下文；
- 推进或恢复业务流程；
- 自行授予权限或保存正式安全审计记录。

完整流程状态由 **L2 流程执行引擎**保存；是否需要人工由规则计算/流程执行等上游能力判断。

## 2. 相比第一版的调整

- 删除“人工接管”；
- 删除 1.11 自己判断的“自动通过”；
- 删除完整 `resume_payload` 的保存和展示；
- 正式处理结果只保留 `approve / modify_approve / reject`；
- 新增统一请求信封字段：`trace_id`、`message_id`、`request_id`、`actor`、`workflow_instance_id`、`node_id`、`task_id`、`idempotency_key` 等；
- 创建接口改为统一的 `accepted / success / failed` 回复；
- 处理完成后返回 `flow.callback` 结果，但不由 1.11 自己恢复流程；
- 模块之间不直连，正式联调通过层接口与对内通道完成。

## 3. 运行方法

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

打开：

- 中文演示台：`http://127.0.0.1:8000`
- 通用 API 测试页：`http://127.0.0.1:8000/api-test`
- FastAPI 接口文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

默认数据库为当前目录下的 `human_collaboration_v1.db`。也可以通过环境变量指定：

```powershell
$env:HUMAN_COLLAB_DB = "D:\data\human_collaboration.db"
uvicorn main:app --reload
```

## 4. 核心接口

| 能力 | 方法与路径 |
|---|---|
| 登记人工待办 | `POST /api/v1/human-tasks` |
| 查询待办列表 | `GET /api/v1/human-tasks` |
| 查询单个待办 | `GET /api/v1/human-tasks/{human_task_id}` |
| 提交真人决定 | `POST /api/v1/human-tasks/{human_task_id}/responses` |
| 催办 | `POST /api/v1/human-tasks/{human_task_id}/reminders` |
| 超时升级登记 | `POST /api/v1/human-tasks/{human_task_id}/escalations` |
| 查询待办日志 | `GET /api/v1/human-tasks/{human_task_id}/logs` |
| 能力清单 | `GET /api/v1/capabilities` |

完整字段见 `API_INTERFACE.md`，请求示例见 `api_examples.json`。

## 5. 本地 Mock 说明

演示页面中的场景按钮会在模块内部构造统一信封，用来模拟：

```text
规则计算等业务引擎发现需要人工
→ L2 流程执行引擎挂起并保存完整流程状态
→ 经 L1 层接口登记 1.11 人工待办
→ 真人处理
→ 1.11 返回人工结果
→ L2 流程执行引擎恢复并推进原流程
```

本地日志仅用于联调验证。正式权限校验、脱敏和审计应由统一层接口、权限管理和安全合规模块完成。

## 6. 自测

```powershell
python test_smoke.py
```

测试通过会显示：`SMOKE TEST PASSED`。
