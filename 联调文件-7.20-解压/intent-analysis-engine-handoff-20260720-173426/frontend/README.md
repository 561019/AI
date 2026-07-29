# IntentTestConsole

研发测试控制台，用于通过浏览器测试完整意图分析引擎。

## 功能

- 输入测试语句
- 发送到 `POST /api/v1/intent/analyze`
- 显示 Level 1 Rule、Level 2 Semantic、Level 3 LLM 判断路径
- 显示后端完整 JSON 返回

## 启动

```powershell
npm install
npm run dev
```

页面地址：

```text
http://localhost:5173/
```

默认请求：

```json
{
  "text": "",
  "user_id": "test_user",
  "conversation_id": "test_session"
}
```
