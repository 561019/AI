# 多媒体生成引擎 v1.1 任务适配版

本目录是交付包内的多媒体生成引擎，路径不依赖本机盘符。进入本目录即可启动。

## 启动

启动前请先启动本地知识库：

```text
..\local_knowledge_base_v0_1
```

启动本引擎：

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8013
```

页面地址：

```text
http://127.0.0.1:8013
```

## 配置

`.env` 默认使用：

```text
KB_BASE=http://127.0.0.1:8012
LLM_PROTOCOL=openai_compatible
LITELLM_BASE=
KIMI_MODEL=kimi
LITELLM_KEY=
```

如果没有大模型配置，请在请求中设置 `use_llm=false`，仍可验证本地知识库取材、方案 Mock、任务适配和 callback。

正式架构中，多媒体凡涉及模型应经 1.5 大模型调度模块。本地版已预留 `model_dispatch_interface_slot` 输入字段和 `model_dispatch_usage` 返回字段；当前 LiteLLM/Kimi 直连只是临时联调替代。

## 主接口

```text
POST /api/multimedia/subtasks
GET  /api/multimedia/tasks/{task_id}
GET  /api/multimedia/capabilities
```

## 支持能力

已对齐多媒体“七项 + 预留”能力接口位，包括 `text_to_image`、`text_to_video`、`video_editing`、`fixed_short_video`、`digital_human`、`text_to_speech`、`media_processing`、`music_sound`、`multilingual_version`。已实现能力返回方案/提示词，未实现能力保留接口位。

## 边界

本引擎当前不生成真实图片、视频、音频文件，只生成方案、提示词、素材引用和接口位结果。
