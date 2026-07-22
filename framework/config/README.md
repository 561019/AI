# 大模型调度配置

统一模型接口：`POST http://127.0.0.1:8002/api/v1/models/responses`

调用链：`业务引擎模块 → 基础层网关(8300) → model.respond → 模型调度模块(8002) → DeepSeek`。

## 使用 model.env

复制 `model.env.example` 为 `model.env`，并填写：

```dotenv
DEEPSEEK_API_KEY=填写真实的DeepSeek_API_Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT_SECONDS=30
```

`start_all.ps1` 会自动读取 `framework/config/model.env`。如果同名环境变量已在 PowerShell 中设置，则以 PowerShell 环境变量为准。

`model.env` 已加入 `.gitignore`，不要把真实密钥写入 `model.env.example` 或提交到版本库。

没有 `DEEPSEEK_API_KEY` 时，模型模块使用 `local-mock`；配置成功并重启后，响应中的 `provider` 为 `deepseek`。
