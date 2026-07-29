# 内容产出与多媒体联调交付包说明

编制日期：2026-07-17

本目录包含四个可交付本地模块，路径均为相对路径。将整个 `交付资料` 文件夹复制到对方电脑后，只要电脑具备 Python 环境，就可以在该目录内启动验证。

## 一、目录结构

```text
交付资料
├─ engines
│  ├─ content_engine_v0_2
│  ├─ multimedia_engine_v1_1
│  ├─ local_knowledge_base_v0_1
│  └─ local_flow_execution_engine
├─ samples
├─ README_交付说明.md
├─ callback字段说明.md
├─ 接口与字段总说明.md
├─ 内容产出与多媒体接口交付清单.md
├─ 联调准备表.txt
├─ 一键安装依赖.bat
├─ 启动全部.bat
├─ 启动全部_不打开页面.bat
└─ 检查服务.bat
```

| 模块 | 相对目录 | 默认端口 |
|---|---|---|
| 内容产出引擎 v0.2 | `.\engines\content_engine_v0_2` | `8011` |
| 多媒体生成引擎 v1.1 | `.\engines\multimedia_engine_v1_1` | `8013` |
| 本地知识库 v0.1 | `.\engines\local_knowledge_base_v0_1` | `8012` |
| 本地流程执行引擎 | `.\engines\local_flow_execution_engine` | `8020` |

## 二、启动方式

推荐方式：

1. 双击 `一键安装依赖.bat`。
2. 双击 `启动全部.bat`，会启动四个本地服务，并打开知识库、内容产出、多媒体、流程执行四个页面。
3. 如果只想启动服务、不打开浏览器页面，双击 `启动全部_不打开页面.bat`。
4. 如需检查服务是否启动成功，双击 `检查服务.bat`。

也可以分别进入各模块目录启动：

```powershell
Set-Location ".\engines\local_knowledge_base_v0_1"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8012
```

```powershell
Set-Location ".\engines\content_engine_v0_2"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8011
```

```powershell
Set-Location ".\engines\multimedia_engine_v1_1"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8013
```

```powershell
Set-Location ".\engines\local_flow_execution_engine"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8020
```

## 三、主要接口

内容产出：

```text
POST /api/content-production/subtasks
GET  /api/content-production/tasks/{content_task_id}
GET  /api/content-production/capabilities
```

多媒体生成：

```text
POST /api/multimedia/subtasks
GET  /api/multimedia/tasks/{task_id}
GET  /api/multimedia/capabilities
```

本地流程执行验证：

```text
POST /api/flow/start
POST /api/flow/decide
POST /api/flow/callback
GET  /api/flow/list
GET  /api/v1/capabilities
```

本地知识库验证：

```text
POST /api/kb/task-materials
GET  /api/health
```

接口简版见 `.\内容产出与多媒体接口交付清单.md`，完整接口和字段见 `.\接口与字段总说明.md`，callback 字段也已汇总在总说明中。

## 四、callback 说明

内容产出和多媒体均支持：

1. 简化回调：传 `callback_url`，协议为 `simple`。
2. 平台信封回调：传 `callback_envelope_url`，协议自动按 `platform_v1`。

状态路径：

```text
accepted -> in_progress -> completed / waiting_human / failed
```

callback 只用于把子任务执行状态和结果回传给流程执行引擎，不承担能力路由、知识库取材或真人确认组织。

## 五、配置说明

多媒体引擎目录下保留了可交付 `.env`，默认不带真实大模型密钥：

```text
KB_BASE=http://127.0.0.1:8012
LLM_PROTOCOL=openai_compatible
LITELLM_BASE=
KIMI_MODEL=kimi
LITELLM_KEY=
```

说明：

1. 当前 `KB_BASE` 指向本地知识库 v0.1，是为了模拟 L1.13 知识库取材服务。正式联调时，应替换为平台或基础模块层提供的知识库检索/取材接口；本模块不应直连知识库数据库，也不调用知识库问答引擎来替代业务执行。
2. 当前 LLM 直连仅用于本地验证。正式架构中，多媒体凡涉及模型均应经大模型调度模块；本版本已预留 `model_dispatch_interface_slot` 和返回字段 `model_dispatch_usage`，内容产出同样不应直接连接模型。
3. 如果对方没有大模型配置，可以把请求里的 `use_llm` 设为 `false`，仍可验证流程派发、知识库取材、Mock 方案和 callback。

## 六、当前边界

已经实现：

1. 四个本地服务可独立启动。
2. 流程执行页面可派发内容产出和多媒体任务。
3. 内容产出可生成文字类本地初稿。
4. 多媒体可通过本地知识库服务取材，并生成方案、提示词和素材引用。
5. 内容产出、多媒体均支持异步 callback。

仍为模拟或接口位：

1. 真实图片、视频、音频文件生成未接入。
2. 正式大模型调度模块未接入；多媒体已预留调度接口位，当前 LLM 直连只是临时代替。
3. 正式知识库、数据模块、数字资产、权限、安全审计、规则计算、产物库仍是接口位或本地模拟。
4. `artifact_ref`、`downloadable_document_ref` 当前是本地占位，不是真实产物库凭证。
