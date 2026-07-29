# permission_gateway

汉和 AI 平台独立权限查验模块。服务在每次调用时从权威数据库实时计算，不维护完整用户权限矩阵，也不使用权限缓存替代数据库。

身份口径只有一套：账号创建时已经实名，`user_id = actor_id = person_id`。`persons` 表只是实名账号在权限域内的档案镜像，不代表另一套“真人”实体；所有 `person_*` 外键均保存同一个账号 ID。

## 环境

- Python 3.11 或更高版本
- 默认 SQLite；第一阶段不对不可信网络开放

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 配置与迁移

复制 `.env.example` 中需要的环境变量到运行环境，然后执行：

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

不设置环境变量时使用 `127.0.0.1:8001` 和 `data/permission.sqlite3`。

## 启动

```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8001
```

停止方法：在前台运行时按 `Ctrl+C`；作为服务运行时向进程发送正常终止信号。

## 测试

```powershell
.\.venv\Scripts\pytest.exe -q
```

## 日志

应用日志输出到标准输出。数据库不可用时，权限异常留痕追加到 `logs/permission-fallback.ndjson`；恢复后运行 `scripts/reconcile_fallback.py` 导入。

## 网关数据导入

```powershell
.\.venv\Scripts\python.exe scripts/import_account_gateway.py ..\account-gateway\audit.db
```

旧通用审计保留在账号网关，不导入权限决策表。

导入程序会把历史网关中分离的 `person_id` 归并到对应 `user_id`。迁移完成后，任何新增或修改数据如果出现账号 ID 与真人 ID 不一致，服务都会拒绝。

## 平台模块接入

业务模块不得直连 `POST /api/permission/check`。该接口只接受 L1 层接口的 `mechanism_direct` 身份；L2 业务引擎通过 `l1-layer-interface` 的 `POST /api/layer/dispatch` 发起标准请求。层接口验证账号网关签发的身份上下文后，才机制性直达权限判定服务。接入前读取 `GET /api/integrations/capabilities`，按 `docs/platform-integration.md` 注册模块动作和服务调用关系；权限控制面使用登记的管理契约。

`POST /api/integrations/events` 是未来异步事件入口，当前固定返回 HTTP 501，避免在服务认证、幂等和事件治理完成前写入权限事实。
