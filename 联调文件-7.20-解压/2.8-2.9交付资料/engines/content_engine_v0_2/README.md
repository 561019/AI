# 内容产出引擎 v0.2 任务适配版

本目录是交付包内的内容产出引擎，路径不依赖本机盘符。进入本目录即可启动。

## 启动

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8011
```

页面地址：

```text
http://127.0.0.1:8011
```

## 主接口

```text
POST /api/content-production/subtasks
GET  /api/content-production/tasks/{content_task_id}
GET  /api/content-production/capabilities
```

## 支持能力

支持营销文案、报告初稿、文章初稿、会议纪要、爆款复用文案、专家方案初稿和通用文字初稿。支持 `callback_url` / `callback_envelope_url` 异步回调。

## 边界

本引擎只负责文字类成果。图片、视频、音频、跨引擎编排和真人确认组织不归本引擎承办。
