# 本地知识库 v0.1 临时接口版

本目录是交付包内的本地知识库，用于给多媒体生成引擎提供素材、模板、风格参考、爆款原件和拆解记录。

## 启动

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8012
```

页面地址：

```text
http://127.0.0.1:8012
```

## 主接口

```text
POST /api/kb/task-materials
GET  /api/health
```

## 边界

本版本是本地临时接口版，未接入真实向量库、权限和文件库。返回的是本地 JSON 中的素材与引用。
