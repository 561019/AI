# Intent Analysis Engine 下一会话加载上下文

更新时间：2026-07-17  
工作区：`D:\AIProjects\intent-analysis-engine`  
用途：新会话开始时优先读取本文，用于快速恢复项目边界、关键决策、完成状态、待办事项、重要文件和整体架构。详细长版交接见 [`CURRENT_PROJECT_HANDOFF.md`](./CURRENT_PROJECT_HANDOFF.md)。

---

## 1. 当前一句话结论

Intent Analysis Engine 当前定位已经明确收敛为：

```text
用户自然语言输入
→ 意图理解
→ 多任务拆解
→ 标准 TaskList 结构化输出
```

项目不负责业务执行，不查真实业务数据，不调用业务执行引擎，不编排业务流程。当前后端完整回归基线：

```text
424 passed, 4 skipped, 2 warnings
```

---

## 2. 当前引擎职责边界

### 2.1 项目负责

- 理解用户自然语言请求。
- 从单句、多轮对话、长文本中发现明确任务。
- 拆解多任务，并建立任务依赖关系。
- 输出标准 TaskList。
- 识别任务动作 `action` 和对象 `object`。
- 识别 `task_type` 并校验其是否已登记。
- 识别 `required_inputs`、`missing_inputs`、不确定输入和冲突输入。
- 生成澄清问题。
- 对 LLM 输出进行代码级契约校验。

### 2.2 项目不负责

- 不调用业务执行引擎。
- 不执行具体业务操作。
- 不查询真实数据库、CRM、财务系统等业务数据。
- 不生成真实报告正文、凭证、审批、邮件、提醒。
- 不做业务流程编排。
- 不根据 Function Registry 执行业务功能。

---

## 3. 不可破坏的关键决策

### 3.1 最终输出只保留 TaskList

对外标准结构：

```json
{
  "tasks": [
    {
      "task_id": "",
      "task_type": "",
      "task_description": "",
      "action": "",
      "object": "",
      "required_inputs": [],
      "missing_inputs": [],
      "dependencies": [],
      "confidence": 0.0
    }
  ],
  "clarification_required": false,
  "clarification_questions": []
}
```

旧字段如 `engine_code`、`target_engine`、`execution_order`、`business_execution` 不能进入最终 TaskList。

### 3.2 Function Registry 只做任务类型登记

Function Registry 只用于：

- 确认 `task_type` 是否存在。
- 约束 `task_type`。
- 提供任务描述。
- 提供 `required_inputs`。

禁止把 Function Registry 当作业务执行路由表。

### 3.3 LLM 只能做理解，不做执行

LLM 只负责：

- 复杂文本理解。
- 任务发现。
- 多任务拆解。
- 任务关系分析。
- 缺失 / 不确定 / 冲突输入识别。

LLM 禁止输出业务执行结果、查询结果、计算结果、报告正文或流程回执。

### 3.4 所有 LLM 输出必须经过代码级校验

不能只依赖 Prompt。LLM 输出进入 TaskList 前必须经过：

- JSON 解析。
- Registry 校验。
- evidence 校验。
- dependency 校验。
- `LLMResponseContractValidator` 契约修正。
- Input Validator。

### 3.5 日常开发默认不使用 Docker

日常开发默认使用：

- Windows PostgreSQL 16。
- 本地虚拟环境 `.venv`。
- NumPy 本地向量仓库。
- 按需 BGE Worker。
- 本地 Vite 前端。

Docker 仅作为完整 Milvus 集成测试或生产部署选项。

---

## 4. 整体架构思路

```text
API / 浏览器输入
  ↓
Conversation Understanding
  - 多轮历史
  - 指代消解
  - 噪声过滤
  - 口语归一化
  ↓
Long Context Task Extraction
  - 长文本分块
  - 背景过滤
  - 全局否定
  - 候选任务抽取
  - 任务合并
  ↓
StandardIntentAnalyzer
  ↓
Level1 Rule Matcher
  ↓ miss
Level2 BGE Semantic Matcher
  ↓ low confidence / miss
Level3 LLM Fallback via Model Gateway
  ↓
LLM Response Contract Validator
  ↓
Registry / Evidence / Dependency Validation
  ↓
Input Validator
  ↓
IntentAnalysisResult / TaskList
```

复杂度路由原则：

```text
LOW    → 规则分析
MEDIUM → BGE 语义分析优先
HIGH   → LLM 分析
```

所有路径最终统一输出 TaskList。

---

## 5. 已完成部分

### 5.1 TaskList 边界重构

已完成：

- 最终输出只保留标准任务清单。
- 移除主链路中的业务执行语义。
- `TaskItem` 支持 `task_description`、`action`、`object`。
- 旧 `task_name` 仅作为兼容别名。
- `IntentAnalysisResult.model_json_schema()` 已面向新 TaskList schema。

关键文件：

- `backend/app/schemas/intent_analysis.py`
- `backend/app/services/intent_analysis_engine/task_factory.py`
- `backend/app/services/intent_analysis_engine/analyzer.py`

### 5.2 长文本任务抽取优化

已完成：

- 背景信息过滤。
- 全局否定 / 暂缓 / 不考虑识别。
- 任务合并机制。
- 动作和对象绑定。
- 输入状态识别：`provided`、`missing`、`uncertain`、`conflict`。
- 澄清问题只来自未解决输入。
- 年度经营复盘长文本回归。

新增 / 重要文件：

- `backend/app/services/task_extraction/global_negation_resolver.py`
- `backend/app/services/task_extraction/task_consolidator.py`
- `backend/app/services/task_extraction/intent_extractor.py`
- `backend/app/services/intent_analysis_engine/input_validator.py`
- `tests/backend/test_long_context_task_extraction.py`
- `tests/backend/test_long_text_regression.py`

### 5.3 Model Gateway 大模型接入层

已完成：

- 新增统一大模型接入层。
- 支持 `deepseek`、`openai`、`mock` provider。
- 业务代码只调用 `ModelGateway`。
- 禁止业务层直接调用 `DeepSeekProvider`。
- DeepSeek 通过 OpenAI-compatible API 接入。
- 失败时自动 fallback 到 mock provider。
- LLM 默认超时已调整为 120 秒，适合长文本。

配置示例：

```env
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=你的key
LLM_MODEL=deepseek-v4-flash
LLM_TIMEOUT_SECONDS=120
```

默认本地开发：

```env
LLM_PROVIDER=mock
```

关键文件：

- `backend/app/services/model_gateway/base.py`
- `backend/app/services/model_gateway/gateway.py`
- `backend/app/services/model_gateway/model_router.py`
- `backend/app/services/model_gateway/providers/deepseek_provider.py`
- `backend/app/services/model_gateway/providers/openai_provider.py`
- `backend/app/services/model_gateway/providers/mock_provider.py`
- `backend/app/services/model_gateway/schemas/llm_response.py`
- `tests/backend/test_llm_model_gateway.py`

### 5.4 LLM Response Contract Validator

已完成代码级契约校验，不能只靠 Prompt。

当前自动修正能力：

- 任意任务存在 `missing_inputs` 时，强制 `clarification_required=true`。
- 自动补充澄清问题。
- 报告生成任务必须依赖分析类任务。
- 如果模型合并“数据整理 + 数据分析”，自动拆成：
  - 整理销售数据
  - 分析销售数据
- 清理非法 `required_inputs`。
- 移除不存在的 dependency。
- 移除自依赖。
- 空 `task_type` / 空 `task_description` 作为契约错误。

关键文件：

- `backend/app/services/model_gateway/contract_validator.py`
- `tests/backend/test_llm_response_contract_validator.py`

### 5.5 Long Text LLM Regression Test

已新增 LLM 长文本回归门槛。

案例文件：

- `evaluation/llm_regression/sales_operation_analysis_case.json`

测试文件：

- `tests/backend/test_llm_long_text_regression.py`

该测试要求必须生成 5 个任务：

1. 整理销售数据
2. 分析销售表现
3. 分析销售下降原因
4. 计算销售人员奖金和提成
5. 生成经营分析材料

禁止生成：

- 智能化平台开发
- 异常监控
- 主动提醒
- 自动发送邮件
- 正式PPT
- 三年历史数据治理

必须触发澄清：

- 提成规则版本
- 计算范围
- 数据来源
- 时间范围

测试指标：

- `task_count`
- `missing_task_count`
- `erroneous_task_count`
- `clarification_correct`
- `dependencies_correct`

默认使用 Fake LLM，不消耗 token。真实模型回归可手动打开：

```powershell
$env:RUN_LIVE_LLM_REGRESSION='1'
```

### 5.6 本地开发与数据库

已完成：

- 本地 PostgreSQL 16.14 对接。
- 默认日常开发不依赖 Docker。
- 本地向量仓库 `.runtime/intent_capability_vectors.npz`。
- BGE Worker 按需启动，空闲释放。
- 前端 / 后端本地启动脚本。

常用命令：

```powershell
cd D:\AIProjects\intent-analysis-engine
.\scripts\start-local.ps1
.\scripts\stop-local.ps1
```

---

## 6. 当前验证基线

完整后端回归：

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest tests\backend -q -p no:cacheprovider
```

当前结果：

```text
424 passed, 4 skipped, 2 warnings
```

LLM 相关专项：

```text
23 passed
```

长期评测基线：

```text
conversation_evaluation_runner.py --semantic-mode local --llm-mode off → 100/100
long_text_evaluation_runner.py --semantic-mode local --llm-mode off → 100/100
```

说明：这些是开发/回归集，不是生产盲测准确率。

---

## 7. 重要文件修改记录

| 文件 / 目录 | 当前职责 |
| --- | --- |
| `backend/app/schemas/intent_analysis.py` | 标准 TaskList schema，隐藏旧内部字段 |
| `backend/app/api/routes/intent.py` | API入口，注入 ModelGateway / Semantic / Conversation 状态 |
| `backend/app/services/intent_analysis_engine/analyzer.py` | Rule → BGE → LLM 主链路与安全校验 |
| `backend/app/services/intent_analysis_engine/llm.py` | LLM证据信封、解析、契约校验接入 |
| `backend/app/services/intent_analysis_engine/input_validator.py` | required_inputs、missing/uncertain/conflict、澄清问题 |
| `backend/app/services/intent_analysis_engine/registry.py` | 只读任务类型登记库 |
| `backend/app/services/intent_analysis_engine/operation_rules.py` | Level1规则匹配 |
| `backend/app/services/conversation_understanding/` | 多轮、指代、噪声、归一化、上下文合并 |
| `backend/app/services/task_extraction/` | 长文本分块、候选抽取、全局否定、任务合并 |
| `backend/app/services/model_gateway/` | 统一大模型接入层 |
| `backend/app/services/model_gateway/contract_validator.py` | LLM输出契约校验与自动修正 |
| `backend/app/config/semantic_capabilities.yaml` | 语义能力库、examples、keywords、required_inputs |
| `backend/app/prompts/intent_analysis_prompt.txt` | Level3 LLM主提示词 |
| `backend/app/prompts/implicit_task_extraction_prompt.txt` | 模板外隐式任务候选抽取 |
| `evaluation/llm_regression/sales_operation_analysis_case.json` | LLM长文本经营分析回归案例 |
| `evaluation/mock_data/context_provider_call.json` | 外部Context Provider mock调用数据 |
| `evaluation/benchmark/` | 生产级盲测数据集、benchmark runner和metrics |
| `evaluation/error_analysis/` | benchmark失败分类、failure_report和优化报告生成 |
| `tests/backend/test_llm_long_text_regression.py` | LLM长文本质量门槛 |
| `tests/backend/test_llm_response_contract_validator.py` | LLM契约修正测试 |
| `docs/api/INTENT_ANALYSIS_API.md` | HTTP API接口文档 |
| `docs/development/EXTERNAL_CONTEXT_CONTRACT.md` | 外部Context模块接口契约 |
| `docs/reports/TEST_RESULTS_20260717.md` | 测试结果报告和截图索引 |
| `.env.example` / `.env.local.example` | 本地/DeepSeek/Mock配置示例 |
| `docs/development/CURRENT_PROJECT_HANDOFF.md` | 详细交接文档 |
| `docs/development/NEXT_SESSION_CONTEXT.md` | 本精简加载文档 |

---

## 8. 当前待办事项

### P0：生产验收前必须做

1. 建立 300-500 条真实脱敏盲测集。  
   当前 100/100 是开发回归集，不可当生产准确率。

2. 对 DeepSeek 真实模型执行 LLM live regression。  
   使用：

   ```powershell
   $env:RUN_LIVE_LLM_REGRESSION='1'
   ```

3. 增加 API 生产保护：
   - 最大文本长度
   - 最大 chunk 数
   - 请求超时
   - 并发限制
   - 模型调用失败熔断

4. 用盲测集校准：
   - `SEMANTIC_THRESHOLD`
   - `LLM_CONFIDENCE_THRESHOLD`
   - LLM 调用触发策略

5. Docker / Milvus 完整集成路径发布前单独验证。

### P1：稳定性与质量

1. 增加 Model Gateway retry/backoff。
2. Debug 中记录 LLM provider、model、耗时、是否 fallback、fallback原因。
3. 增加 token 使用量统计，但禁止记录 API Key。
4. 把完整 pytest、对话评测、长文本评测、LLM回归接入 CI。
5. 增加无任务负样本、引用他人要求、已完成事项、未来规划等长文本负样本。
6. 继续降低本地规则路径对“监控/提醒/未来规划”的误报风险。

### P2：演示与工程完善

1. 前端增加 conversation_id / history 测试能力。
2. 前端增加 debug 详情面板，但默认保持简洁。
3. 清理旧版 `intent_analyzer` / `llm_engine` 兼容模块前，先确认没有外部依赖。
4. 更新 README 和启动说明，避免用户在 `C:\Users\PC` 下误执行项目脚本。

---

## 9. 下次会话启动建议

### 9.1 首先读取

```text
docs/development/NEXT_SESSION_CONTEXT.md
docs/development/CURRENT_PROJECT_HANDOFF.md
```

### 9.2 确认虚拟环境

```powershell
cd D:\AIProjects\intent-analysis-engine
.\.venv\Scripts\python.exe --version
```

### 9.3 运行关键回归

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest tests\backend\test_llm_long_text_regression.py tests\backend\test_llm_response_contract_validator.py -q -p no:cacheprovider
```

完整回归：

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest tests\backend -q -p no:cacheprovider
```

### 9.4 本地启动

```powershell
.\scripts\start-local.ps1
```

停止：

```powershell
.\scripts\stop-local.ps1
```

### 9.5 DeepSeek配置检查

不要打印真实 key，只检查是否存在：

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -c "from app.core.config import settings; print(settings.llm_provider, settings.llm_base_url, settings.llm_model, bool(settings.llm_api_key))"
```

期望类似：

```text
deepseek https://api.deepseek.com deepseek-v4-flash True
```

---

## 10. 当前推荐下一步

最值得继续做的是：

1. 运行一次真实 DeepSeek live regression，确认 `sales_operation_analysis_case.json` 在真实模型下是否通过。
2. 给 Model Gateway 增加耗时、fallback、provider/model debug 字段。
3. 补充一批“未来规划 / 不包含 / 不需要 / 暂缓”的长文本负样本。
4. 建立真实脱敏盲测集，开始校准 LLM 与 BGE 的触发边界。

---

## 11. 重要提醒

- 不要把 DeepSeek / OpenAI API Key 写进代码、测试、文档或日志。
- 不要启动 Docker，除非明确要验证 Milvus 或生产部署路径。
- 不要把 LLM 当业务执行器。
- 不要为了通过测试硬编码单个输入文本。
- 不要修改 TaskList 契约，除非同步更新所有回归测试和交接文档。
