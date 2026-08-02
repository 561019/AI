# 大模型调度配置

统一模型接口：`POST http://127.0.0.1:8002/api/v1/models/responses`

调用链：`业务引擎模块 → 基础层网关(8300) → model.respond → 模型调度模块(8002) → DeepSeek`。

## 使用 model.env

复制 `model.env.example` 为 `model.env`，并填写 DeepSeek 配置：

```dotenv
DEEPSEEK_API_KEY=填写真实的 DeepSeek API Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=填写已开通的 DeepSeek 模型 ID
DEEPSEEK_TIMEOUT_SECONDS=30
```

`start_all.ps1` 会自动读取 `framework/config/model.env`。如果同名环境变量已在 PowerShell 中设置，则以 PowerShell 环境变量为准。

`model.env` 已加入 `.gitignore`，不要把真实密钥写入 `model.env.example` 或提交到版本库。

没有 DeepSeek API Key 时，模型模块使用 `local-mock`；配置成功并重启后，响应中的 `provider` 为 `deepseek`。

## 使用豆包

豆包通过火山方舟的 OpenAI 兼容接口接入。将以下内容填入 `model.env`，并把 `MODEL_PROVIDER` 改为 `doubao`：

```dotenv
MODEL_PROVIDER=doubao
DOUBAO_API_KEY=填写真实的豆包/方舟 API Key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=填写已开通模型的模型 ID 或推理接入点 ID
DOUBAO_TIMEOUT_SECONDS=30
```

火山方舟的 ChatCompletions 接口使用 `/api/v3/chat/completions`，`model` 可填写模型 ID 或推理接入点 ID。[火山方舟 API 文档](https://api.volcengine.com/api-docs/view?action=ChatCompletions&serviceCode=ark&version=2024-01-01)
