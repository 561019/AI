# Conversation Understanding Layer

更新时间：2026-07-13

## 1. 目标与边界

Conversation Understanding Layer 是 Intent Analysis Engine 的新入口层，用于处理长文本、多轮对话、口语表达、背景信息和指代。它只做请求理解与结构化，不执行业务任务，不查询真实业务数据，不猜测缺失业务规则，也不改变标准 `IntentAnalysisResult` / TaskList 对外契约。

现有核心模块保持不变：

```text
Rule Matcher
Semantic Matcher (BGE)
Task Builder
Input Validator
```

## 2. 新架构

```text
HTTP text + optional history
  -> ConversationStateStore (Postgres, latest N messages)
  -> merge stored history + explicit history
  -> ReferenceResolver
  -> NoiseFilter
  -> NaturalLanguageNormalizer
  -> ContextExtractor
  -> ConversationParser / task segments
  -> Existing StandardIntentAnalyzer (each segment)
       -> Rule Matcher
       -> Semantic Matcher (BGE)
       -> LLM fallback
       -> Task Builder
       -> Input Validator
  -> Task merge / dependency remap
  -> standard IntentAnalysisResult
```

多任务片段逐个进入现有 Analyzer。对话层只注入用户明确表达的时间、对象、范围、组织、统计字段等输入，并再次调用现有 `TaskInputValidator`。未明确提供的提成政策、文件、数据来源等不会被自动补全。

## 3. 新增模块

- `backend/app/services/conversation_understanding/conversation_parser.py`
  - 工作副本归一化、任务片段拆解、结果合并、依赖重映射和入口编排。
- `backend/app/services/conversation_understanding/context_extractor.py`
  - 提取目标、动作、业务对象、约束、时间、人员组织、数据范围和统计字段。
- `backend/app/services/conversation_understanding/noise_filter.py`
  - 过滤礼貌表达、情绪表达、催促信息和纯背景说明。
- `backend/app/services/conversation_understanding/reference_resolver.py`
  - 基于服务端状态和调用方历史消解“这个、那个、上面的、刚才那个、继续”等指代。
- `backend/app/services/conversation_understanding/state_store.py`
  - 定义状态存储抽象，提供 Postgres 和线程安全内存实现。
- `backend/app/repositories/conversation_state_repository.py`
  - 按 `user_id + conversation_id` 读写最近会话消息。
- `backend/app/models/conversation_message.py`
  - 保存用户原话、角色、分析摘要和创建时间，不保存业务执行结果。

## 4. API 变化

原单轮请求继续兼容：

```json
{
  "text": "分析今年销售情况",
  "user_id": "user-001",
  "conversation_id": "conversation-001"
}
```

调用方仍可显式提供多轮格式：

```json
{
  "text": "那再看看利润情况",
  "conversation_id": "conversation-001",
  "history": [
    {"role": "user", "text": "帮我分析销售数据"},
    {"role": "assistant", "text": "已识别销售分析任务"}
  ]
}
```

`history` 同时接受字符串消息以及使用 `content` 或 `message` 字段的消息对象。即使不传 `history`，相同 `user_id + conversation_id` 的后续请求也会自动读取服务端历史。未传 `user_id` 时使用 `anonymous`，未传 `conversation_id` 时自动生成。对外响应仍是原标准 TaskList 契约；解析细节仅在 `debug=true` 时出现在 `conversation_understanding`、`conversation_state` 和 `segment_analyses`。

## 5. 关键行为

- `original_text` 永远保存用户原话，`normalized_text` 只存在于对话理解 debug。
- 新一轮明确给出新对象时优先使用新对象，例如从“销售”切换到“利润”。
- 只有当前轮省略对象或使用指代时，才从历史继承已明确表达的信息。
- 服务端历史按 `user_id + conversation_id` 隔离，默认只读取最近 20 条，可通过 `CONVERSATION_HISTORY_LIMIT` 配置为 1-200。
- 显式 `history` 与服务端历史按角色和文本去重后合并。
- 状态读写失败不会改变正常 TaskList；错误只在 `debug.conversation_state` 中显示。
- 多任务按出现顺序生成 `execution_order`，后一任务依赖前一任务。
- 无法识别任务，或缺少历史的“继续上面的”，必须返回澄清。
- “没有文件”“未提供附件”等否定表达不会被当成已提供输入。
- 旧拆解结果中非用户明确提供的提成政策会在最终校验前移除并触发澄清。

## 6. 评测

数据集：`evaluation/conversation_dataset.json`

- 100 条复杂对话。
- 覆盖长文本、口语、背景、多任务、多轮、指代和无效信息干扰。
- 每条记录包含 `conversation`、`expected_tasks`、`expected_engine` 和 `should_clarify`。

运行：

```powershell
.venv\Scripts\python.exe conversation_evaluation_runner.py --semantic-mode local --llm-mode off --output evaluation\conversation_report.json
```

2026-07-13 当前离线评测：

```text
完全通过: 100/100
engine识别准确率: 100.00%
task_type准确率: 100.00%
clarification准确率: 100.00%
任务拆解准确率: 100.00%
```

澄清标注已经与 required_inputs 原则对齐：未提供统计范围、汇总字段、数据来源或前序实际结果时必须澄清，不以任务已识别为理由自动补全。

## 7. 数据库迁移

新增表：`conversation_message`

迁移版本：`20260713_0003`

- `20260713_0002`：创建 `conversation_message`。
- `20260713_0003`：幂等补齐 11 个 `ENG_*` 引擎注册记录，保证意图审计外键有效。

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
```

容器镜像已包含 Alembic 文件，也可执行：

```powershell
docker compose exec backend alembic upgrade head
```
