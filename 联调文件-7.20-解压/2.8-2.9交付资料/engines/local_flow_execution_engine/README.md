# 本地简化流程执行引擎

本目录是交付包内的本地流程执行引擎，用于验证“流程执行引擎派发任务 -> 内容产出/多媒体承办 -> 结果返回/回调”的框架逻辑。

## 启动

请先启动：

```text
..\local_knowledge_base_v0_1
..\content_engine_v0_2
..\multimedia_engine_v1_1
```

再启动本引擎：

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8020
```

页面地址：

```text
http://127.0.0.1:8020
```

## 默认依赖地址

```text
CONTENT_BASE=http://127.0.0.1:8011
MEDIA_BASE=http://127.0.0.1:8013
```

## 主接口

```text
POST /api/flow/start
POST /api/flow/decide
POST /api/flow/callback
GET  /api/flow/list
GET  /api/v1/capabilities
```

## 边界

流程实例登记、节点状态和本地派发是真实逻辑；权限、安全、真实工作台待办、真实产物库仍为模拟或接口位。
