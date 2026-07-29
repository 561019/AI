# Intent Analysis Engine 项目上下文文档

> 用途：这份文档可以直接复制给 ChatGPT 或其他协作方，让对方快速理解当前项目，后续你再问架构、接口、联调、测试、优化建议时，不需要重新解释项目背景。

## 1. 项目一句话说明

Intent Analysis Engine 是一个企业自然语言意图分析引擎。它把用户输入的中文自然语言请求解析成标准化 `TaskList`，供后续流程执行引擎消费。

它负责：

- 识别用户想做什么任务。
- 抽取任务类型、动作、对象、依赖关系、必要输入和缺失输入。
- 判断是否需要澄清。
- 利用上下文处理“接着改”“再算一遍”“换个维度看看”等省略表达。
- 对多任务句子做分段识别，并在 L1/L2 只命中部分任务时，仅把未覆盖片段送到 L3 大模型。
- 输出结构化任务清单。

它不负责：

- 不执行真实业务任务。
- 不查询 ERP、CRM、OA 等真实业务系统。
- 不生成最终业务报告、文档或图片。
- 不发送真实提醒。
- 不编排流程执行。
- 不建设 Context & Prompt Management 系统。
- 不保存或管理长期上下文记忆。

## 2. 当前模块边界

本项目处在企业智能体链路中的“意图分析层”。

推荐整体链路：

```text
用户输入
  -> 上下文管理模块
  -> Intent Analysis Engine
  -> TaskList
  -> 流程执行引擎
  -> 业务工具 / 业务系统 / 人工审批 / 文档生成等
```

Intent Analysis Engine 和外部模块的边界如下：

| 模块 | 归属 | 本项目职责 |
| --- | --- | --- |
| Context 管理模块 | 外部依赖 | 本项目只调用并消费 context |
| Prompt 管理模块 | 外部依赖 | 本项目不建设独立 Prompt Management |
| LLM Provider | 外部服务 | 本项目通过 Model Gateway 调用 |
| 流程执行引擎 | 外部下游 | 本项目只输出 TaskList，不执行 |
| Function Registry | 本项目内只做注册/校验 | 不是业务执行路由表 |
| Benchmark 评测体系 | 本项目内 | 用于验证规则、语义、澄清、否定、上下文等能力 |

## 3. 主要目录

```text
backend/
  app/
    api/routes/intent.py
    schemas/
    services/
      intent_analysis_engine/
      context_provider/
      model_gateway/
      semantic/
      task_extraction/

database/
  init/

docs/
  api/
  delivery/
  development/
  reports/

evaluation/
  benchmark/
    datasets/
      train/
      validation/
      blind_test/
    metrics/
    benchmark_runner.py
  error_analysis/
  mock_data/

frontend/
offline-demo/
scripts/
tests/
```

重要文件：

| 文件 | 作用 |
| --- | --- |
| `README.md` | 项目启动、测试、配置总入口 |
| `docs/api/INTENT_ANALYSIS_API.md` | HTTP API 合同 |
| `docs/development/EXTERNAL_CONTEXT_CONTRACT.md` | 外部上下文模块接口约定 |
| `docs/delivery/HANDOFF_RUNBOOK.md` | 交付给他人联调的运行手册 |
| `docs/delivery/PACKAGE_VERIFICATION.md` | 打包前验证记录 |
| `backend/app/api/routes/intent.py` | 意图分析 API 路由 |
| `backend/app/schemas/intent_analysis.py` | TaskList / TaskItem 输出 schema |
| `backend/app/services/intent_analysis_engine/analyzer.py` | 标准意图分析主流程 |
| `backend/app/services/intent_analysis_engine/operation_rules.py` | L1 确定规则 |
| `backend/app/services/intent_analysis_engine/partial_coverage_detector.py` | 部分覆盖检测 |
| `backend/app/services/intent_analysis_engine/input_validator.py` | task-level 输入校验和澄清 |
| `backend/app/services/intent_analysis_engine/clarification/` | 澄清会话恢复机制 |
| `backend/app/services/context_provider/` | 外部上下文 Provider 抽象和 mock |
| `backend/app/services/model_gateway/` | LLM 调用、重试、fallback、日志 |
| `evaluation/benchmark/` | 生产级 benchmark 数据集和 runner |
| `evaluation/error_analysis/` | 失败案例分类和优化报告 |

## 4. 对外 HTTP API

本地默认服务：

```text
Backend:  http://127.0.0.1:8000/
API docs: http://127.0.0.1:8000/docs
Frontend: http://127.0.0.1:5173/
```

核心接口：

```text
POST /api/v1/intent/analyze
POST /api/v1/intent/clarification/answer
GET  /api/v1/intent/history
GET  /health
GET  /health/ready
```

### 4.1 意图分析接口

```text
POST /api/v1/intent/analyze
```

请求：

```json
{
  "text": "整理销售数据，计算销售提成，生成经营报告",
  "user_id": "user-001",
  "conversation_id": "conversation-001",
  "project_id": "project-001",
  "history": [
    {
      "role": "user",
      "text": "计算2025年销售提成"
    }
  ],
  "debug": true
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `text` | string | 是 | 当前用户输入 |
| `user_id` | string | 否 | 用户 ID，默认 `anonymous` |
| `conversation_id` | string | 否 | 会话 ID，默认自动生成 |
| `project_id` | string/null | 否 | 当前项目 ID，用于调用外部 Context Provider |
| `history` | array | 否 | 显式传入的历史会话 |
| `debug` | boolean | 否 | 是否返回内部分析诊断信息 |

响应主结构：

```json
{
  "success": true,
  "data": {
    "tasks": [],
    "clarification_required": false,
    "global_clarification_required": false,
    "clarification_questions": []
  },
  "error": null,
  "debug": null
}
```

### 4.2 澄清回答接口

```text
POST /api/v1/intent/clarification/answer
```

用途：当首次分析发现某个 task 缺输入时，系统会创建澄清会话。用户补充信息后，调用该接口把答案回填到原 task。

请求：

```json
{
  "clarification_session_id": "CS-xxx",
  "answer": "使用2026规则，华东区域，ERP数据"
}
```

响应：

```json
{
  "task_id": "原任务ID",
  "status": "ready",
  "missing_inputs": [],
  "final_inputs": {
    "calculation_policy": "2026规则",
    "data_scope": "华东区域",
    "data_source": "ERP"
  },
  "clarification_questions": [],
  "clarification_session_id": "CS-xxx",
  "session_status": "COMPLETED"
}
```

强约束：

- 用户补充不能创建新的 `task_id`。
- 必须保留原始 `task_id`。
- 只回填原 task 的缺失字段。
- 回填后重新执行 task-level input validation。

## 5. TaskList 输出格式

标准输出是 `TaskList`，每个任务是一个 `TaskItem`。

```json
{
  "tasks": [
    {
      "task_id": "T001",
      "task_type": "RULE_CALCULATION_COMMISSION",
      "task_description": "计算销售提成",
      "action": "计算",
      "object": "销售提成",
      "required_inputs": [
        "calculation_policy",
        "calculation_basis"
      ],
      "missing_inputs": [
        "calculation_policy"
      ],
      "clarification_session_id": "CS-001",
      "clarification_required": true,
      "clarification_questions": [
        "请补充销售提成计算使用的政策或规则。"
      ],
      "status": "needs_clarification",
      "blocked_reason": null,
      "dependencies": [],
      "confidence": 0.92
    }
  ],
  "clarification_required": true,
  "global_clarification_required": true,
  "clarification_questions": []
}
```

task 状态：

| 状态 | 含义 |
| --- | --- |
| `ready` | 输入完整，下游流程执行引擎可以执行 |
| `needs_clarification` | 当前 task 缺输入、存在冲突或不确定，需要用户补充 |
| `waiting_dependency` | 依赖的前置 task 尚未 ready |

全局澄清规则：

```text
任意 task.clarification_required = true
=> global_clarification_required = true
=> clarification_required = true
```

重要原则：

- 澄清问题必须绑定到具体 task。
- 不允许把不同 task 的 missing_inputs 混在一起。
- 不允许生成无法归属到 task 的全局问题。
- 兼容全局字段，但业务判断应优先看每个 task 的状态。

## 6. 当前支持的主要任务类型

当前任务类型由 Function Registry 和规则/语义/LLM 共同约束。常见 task_type 包括：

| task_type | 说明 |
| --- | --- |
| `DOCUMENT_TABLE_PARSE` | 文档/表格解析 |
| `FILE_STRUCTURE_EXTRACT` | 文件结构提取 |
| `EXTERNAL_DATA_FETCH` | 外部系统数据获取 |
| `EXTERNAL_SYSTEM_SUBMIT` | 外部系统提交/写入 |
| `DATA_QUERY_FETCH` | 查询或获取业务数据 |
| `DATA_AGGREGATION_SUMMARY` | 数据统计汇总 |
| `DATA_ANALYSIS_GROUP_SUM` | 分组求和 |
| `DATA_ANALYSIS_PIVOT` | 数据透视 |
| `DATA_FILTER` | 数据筛选 |
| `DATA_SORT` | 数据排序 |
| `COMPLAINT_INFORMATION_ORGANIZE` | 投诉信息整理 |
| `RULE_CALCULATION_GENERAL` | 通用规则计算 |
| `RULE_CALCULATION_COMMISSION` | 销售提成/佣金计算 |
| `DATA_ANALYSIS_PROBLEM` | 问题/原因分析 |
| `DATA_ANALYSIS_YOY` | 同比分析 |
| `DATA_ANALYSIS_MOM` | 环比分析 |
| `DATA_ANALYSIS_FORECAST` | 预测分析 |
| `QUESTION_ANSWER` | 知识问答 |
| `DOCUMENT_GENERATE` | 业务文档/报告生成 |
| `CONTENT_GENERATE` | 普通文本内容生成 |
| `IMPROVEMENT_PLAN_GENERATE` | 改进方案生成 |
| `MULTIMEDIA_GENERATE` | 图片/视频/音频等多媒体内容生成 |
| `PROCESS_HANDLE` | 业务流程办理 |
| `WORKFLOW_START` | 发起业务流程 |
| `MONITORING_REMINDER` | 监控/提醒任务 |
| `DIGITAL_ASSET_ACCRUAL_VOUCHER` | 数字资产/凭证类任务 |

注意：这些任务类型只表示“用户想做什么”。它们不是本项目直接执行的业务能力。

## 7. 多级意图判断机制

当前设计是 L1/L2/L3 多级判断。

### 7.1 L1 Rule Matching

L1 是确定性规则层，处理高确定表达。

特点：

- 速度快。
- 可解释。
- 只适合明确表达。
- 禁止为了提高召回随意扩大关键词。
- L1 扩展必须由 benchmark validation 失败案例驱动。

典型例子：

```text
生成销售报表
计算销售提成
整理销售数据
发起报销流程
解析 Excel 表格
```

### 7.2 L2 Semantic Matching

L2 是语义匹配层，用于识别同义、近义、口语表达。

特点：

- 依赖 semantic examples / semantic descriptions / embedding。
- 适合“帮我看看销售为什么下降”这种不完全关键词化的表达。
- 扩展时应新增语义样例，不应把模糊表达硬塞进 L1。

典型例子：

```text
帮我看看销售为什么下降
换个维度看看
看看客户投诉主要集中在哪些问题
```

### 7.3 L3 LLM Analysis

L3 是大模型理解层。

触发场景：

- L1/L2 完全无法判断。
- L1/L2 只覆盖了多任务输入的一部分。
- 长文本需求需要抽取多个任务。
- 表达存在复杂上下文或需要推理。

限制：

- 不整句盲目调用 LLM。
- 如果 L1/L2 已覆盖部分任务，只把 uncovered segments 送 L3。
- LLM 输出必须通过代码级 schema 校验和 task_type 校验。
- LLM 不能无依据扩展任务。
- context 不足时应返回 `clarification_required=true`。

## 8. Partial Coverage Detector

新增文件：

```text
backend/app/services/intent_analysis_engine/partial_coverage_detector.py
```

目标：解决多任务输入中，L1/L2 只命中部分任务后，剩余动作没有进入 L3 的问题。

流程：

```text
Input
  -> Task Segmenter
  -> L1 Matching
  -> L2 Semantic Matching
  -> Partial Coverage Detector

如果 coverage = 100%:
  结束，不调用 L3

如果 coverage < 100%:
  提取 uncovered_segments
  -> L3
  -> Task Merge
  -> Final TaskList
```

Detector 输出：

```json
{
  "coverage_rate": 0.67,
  "covered_segments": [],
  "uncovered_segments": [],
  "need_llm": true
}
```

debug 输出包含：

```json
{
  "l1_tasks": [],
  "l2_tasks": [],
  "coverage_rate": 0.67,
  "covered_segments": [],
  "uncovered_segments": [],
  "need_llm": true,
  "llm_called": true,
  "uncovered_segment_count": 2,
  "l3_compensation_success": true
}
```

关键规则：

- 已识别 task 必须绑定原文 segment。
- 禁止只通过关键词判断 coverage。
- 只把未覆盖片段交给 L3。

例子：

```text
输入：整理销售数据，分析下降原因，生成报告

L1 命中：
- 整理销售数据

Detector 发现未覆盖：
- 分析下降原因
- 生成报告

最终输出：
- 数据整理任务
- 销售下降原因分析任务
- 报告生成任务
```

## 9. 否定和 Future Scope Filter

本项目增强了 Task Extraction 的全局否定解析和未来规划过滤。

目标：避免把“未来想做但本次不做”的内容误识别为当前任务。

典型问题：

```text
主动提醒负责人。
本次任务范围里面不包含异常监控和主动提醒功能。
```

如果前文产生了“监控负责人/提醒负责人”任务，后文明确排除，则应撤销。

Future Scope Filter 识别表达：

```text
未来规划
以后
后续
未来考虑
暂不需要
目前不包含
本次不做
不考虑
```

规则：

```text
如果任务候选来自未来规划描述，且后文明确排除，则删除任务。
```

测试目标：

```text
输入：
以后希望自动提醒异常情况，但本次不考虑。

输出不能包含：
- 异常监控任务
- 提醒任务
```

## 10. 上下文调用能力

本项目新增 Context Provider，但 Context 模块是外部依赖。

目录：

```text
backend/app/services/context_provider/
  base.py
  client.py
  schemas.py
  mock_provider.py
```

### 10.1 本项目期望外部上下文模块提供的接口

Python 适配接口：

```python
class BaseContextProvider:
    def get_context(
        self,
        user_id: str,
        conversation_id: str,
        project_id: str | None = None,
    ) -> ContextProviderResponse:
        ...
```

返回：

```json
{
  "conversation_context": [],
  "project_context": [],
  "user_project_context": []
}
```

含义：

| 字段 | 含义 | 优先级 |
| --- | --- | --- |
| `conversation_context` | 当前 conversation 上下文 | 最高 |
| `project_context` | 当前 project 上下文 | 中 |
| `user_project_context` | 用户历史 project 上下文 | 低 |

优先级：

```text
conversation > project > historical_projects
```

冲突处理：

```text
近距离上下文覆盖远距离上下文。
同一 scope 内，较新的 item 覆盖较旧 item。
```

建议 context item：

```json
{
  "task_type": "RULE_CALCULATION_COMMISSION",
  "task_description": "计算销售提成",
  "source_text": "计算2025年销售提成",
  "action": "计算",
  "object": "销售提成",
  "created_at": "2026-07-17T08:00:00Z",
  "metadata": {
    "source": "context-service",
    "turn_id": "turn-001"
  }
}
```

### 10.2 统一输入格式

Rule / BGE / LLM 统一消费：

```json
{
  "user_input": "帮我再算一遍",
  "context": {
    "current_conversation": {
      "items": []
    },
    "current_project": {
      "items": []
    },
    "historical_projects": {
      "items": []
    }
  }
}
```

### 10.3 省略表达支持

已覆盖的典型省略表达：

```text
帮我再算一遍
重新计算
接着改
换个维度看看
```

预期行为：

| 当前输入 | 上下文 | 预期识别 |
| --- | --- | --- |
| `帮我再算一遍` | 上一轮是销售提成计算 | 重新执行销售提成计算任务 |
| `重新计算` | 上一轮是计算任务 | 关联上一轮计算任务 |
| `接着改` | 上一轮是报告生成任务 | 关联上一轮报告生成任务 |
| `换个维度看看` | 上一轮是分析任务 | 关联上一轮分析任务 |

如果 context 不足：

```json
{
  "tasks": [],
  "clarification_required": true,
  "clarification_questions": [
    "请明确要继续处理的上一轮任务或业务对象。"
  ]
}
```

## 11. LLM Prompt 和 Model Gateway

L3 模型输入必须包含：

```text
当前输入 + context
```

Prompt 限制：

- 禁止无依据扩展任务。
- 禁止从 context 单独发明当前用户没有要求的任务。
- context 不足时返回 clarification。
- 输出必须符合标准 schema。

Model Gateway 生产稳定性：

| 能力 | 当前设计 |
| --- | --- |
| 默认超时 | `LLM_TIMEOUT_SECONDS=120` |
| 最大重试 | 3 次 |
| 退避 | 2s / 5s / 10s |
| fallback | DeepSeek/OpenAI 失败后 fallback 到 mock provider |
| debug 日志 | provider、model、request_id、耗时、retry 次数、fallback 状态 |
| 禁止日志 | API_KEY |

`.env.example` 推荐本地默认：

```env
LLM_PROVIDER=mock
LLM_MODEL=mock-llm
LLM_TIMEOUT_SECONDS=120
```

DeepSeek 示例：

```env
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_API_KEY=your-api-key
LLM_TIMEOUT_SECONDS=120
```

mock fallback 必须明确标识：

```json
{
  "fallback": true,
  "provider": "mock"
}
```

禁止把 mock 输出伪装成真实模型结果。

## 12. Task-level 澄清机制

当前澄清机制已经从 global clarification 改成 task-level clarification。

流程：

```text
Task Extraction
  -> Task Input Validator
  -> Task-level Clarification Generator
  -> TaskList 输出
```

每个 task 独立维护：

```json
{
  "task_id": "T001",
  "task_type": "RULE_CALCULATION_COMMISSION",
  "missing_inputs": [
    "calculation_policy"
  ],
  "clarification_required": true,
  "clarification_questions": [
    "请补充销售提成计算规则。"
  ],
  "status": "needs_clarification"
}
```

依赖处理：

```text
如果前置 task 缺输入：
后续依赖 task.status = waiting_dependency
```

例子：

```text
输入：
整理销售数据，计算销售提成，生成经营报告

预期：
Task1 数据整理
- status=ready

Task2 提成计算
- missing_inputs 包含提成规则/计算依据
- status=needs_clarification

Task3 报告生成
- dependencies 指向 Task1 / Task2
- 如果依赖未 ready，则 status=waiting_dependency
```

## 13. 澄清恢复机制

目录：

```text
backend/app/services/intent_analysis_engine/clarification/
  session_manager.py
  answer_mapper.py
  clarification_state.py
```

状态对象：

```json
{
  "clarification_session_id": "CS001",
  "task_id": "T001",
  "original_task": {},
  "missing_inputs": [],
  "questions": [],
  "received_answers": {},
  "status": "WAITING_USER_INPUT"
}
```

status：

```text
WAITING_USER_INPUT
ANSWER_RECEIVED
VALIDATING
COMPLETED
FAILED
```

流程：

```text
首次分析
  -> task 缺输入
  -> 输出 TaskList
  -> 创建 ClarificationSession

用户补充
  -> 不重新生成 task
  -> Answer Mapper
  -> 映射回答到原 task missing_inputs
  -> 更新 inputs
  -> Task Input Validator 重新校验
  -> 更新 task 状态
```

典型测试：

```text
第一次：
计算销售提成

返回：
task.status = needs_clarification
task.clarification_session_id = CS-xxx

第二次：
使用2026规则，华东区域，ERP数据

返回：
同一个 task_id
status = ready
missing_inputs = []
final_inputs = {
  "calculation_policy": "2026规则",
  "data_scope": "华东区域",
  "data_source": "ERP"
}
```

## 14. 流程执行引擎对接约定

Intent Analysis Engine 的下游是流程执行引擎。建议流程执行引擎提供一个接收 TaskList 的接口。

推荐接口：

```text
POST /workflow/tasklists
```

推荐请求：

```json
{
  "request_id": "REQ-001",
  "user_id": "user-001",
  "conversation_id": "conversation-001",
  "project_id": "project-001",
  "source": "intent-analysis-engine",
  "tasks": [
    {
      "task_id": "T001",
      "task_type": "DATA_QUERY_FETCH",
      "task_description": "整理销售数据",
      "action": "整理",
      "object": "销售数据",
      "status": "ready",
      "dependencies": [],
      "required_inputs": [],
      "missing_inputs": [],
      "confidence": 0.9
    }
  ],
  "global_clarification_required": false
}
```

流程执行引擎应遵守：

- 只执行 `status=ready` 的 task。
- 跳过或等待 `needs_clarification` 的 task。
- 对 `waiting_dependency` 的 task 等依赖 ready 后再执行。
- 不修改 `task_id`。
- 按 `dependencies` 处理前后置关系。
- 对不支持的 `task_type` 返回明确错误，不要静默忽略。
- 返回执行状态、执行 ID、失败原因。

建议响应：

```json
{
  "accepted": true,
  "workflow_run_id": "WR-001",
  "task_acceptance": [
    {
      "task_id": "T001",
      "accepted": true,
      "execution_status": "queued",
      "reason": null
    }
  ]
}
```

本项目不会自己执行这些 task。

## 15. Mock 数据和离线验证

已有 mock 能力：

| Mock | 位置 | 用途 |
| --- | --- | --- |
| Context Provider mock | `backend/app/services/context_provider/mock_provider.py` | 测试上下文依赖 |
| Context mock call | `evaluation/mock_data/context_provider_call.json` | 展示外部上下文调用数据 |
| LLM mock provider | `backend/app/services/model_gateway/providers/mock_provider.py` | 本地开发和 fallback |
| offline demo | `offline-demo/intent-offline-demo.html` | 不依赖后端/数据库/模型服务的演示 |

本地开发建议默认使用：

```env
LLM_PROVIDER=mock
VECTOR_BACKEND=local
```

真实 LLM API key 不应放入提交文件、截图、日志或交付压缩包。

## 16. Benchmark 和错误分析

生产级 benchmark 目录：

```text
evaluation/benchmark/
  datasets/
    train/
    validation/
    blind_test/
  metrics/
  benchmark_runner.py
```

v1 数据集：

```text
总数：300 条脱敏企业语料
train: 180
validation: 60
blind_test: 60
```

样本格式：

```json
{
  "id": "BENCH-VALIDATION-001",
  "text": "用户原始输入",
  "intent_category": "",
  "expected_tasks": [],
  "expected_task_types": [],
  "required_clarification": true,
  "missing_inputs": [],
  "forbidden_tasks": []
}
```

覆盖范围：

```text
1. 短指令
2. 长文本需求
3. 口语表达
4. 省略表达
5. 多任务请求
6. 否定表达
7. 未来规划
8. 上下文依赖
9. 信息不足
10. 歧义请求
```

运行 validation：

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe evaluation\benchmark\benchmark_runner.py --split validation --semantic-mode local --llm-mode off
```

blind_test 要求显式开关：

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe evaluation\benchmark\benchmark_runner.py --split blind_test --allow-blind-test --semantic-mode local --llm-mode off
```

约束：

- `blind_test` 禁止参与规则开发。
- L1/L2 扩展必须由 validation 失败案例驱动。
- 禁止凭经验直接加大关键词范围。

错误分析目录：

```text
evaluation/error_analysis/
  failure_classifier.py
  report_generator.py
```

失败报告 schema：

```json
{
  "text": "",
  "expected_tasks": [],
  "actual_tasks": [],
  "error_type": "",
  "confidence": ""
}
```

失败类型：

| error_type | 含义 | 处理方式 |
| --- | --- | --- |
| `L1_RULE_MISS` | 高确定表达但规则未命中 | 只增加确定 L1 规则 |
| `L2_SEMANTIC_MISS` | 同义/口语/业务近义表达未识别 | 扩展 semantic examples/descriptions |
| `NEED_L3_OR_CLARIFICATION` | 歧义或信息不足 | 不加规则，进入 L3 或澄清 |

指标：

```text
task_type accuracy
task recall
forbidden task rate
future_scope false positive
negation accuracy
clarification accuracy
partial_coverage_rate
uncovered_segment_count
L3 补偿成功率
```

回滚条件：

```text
如果 task 准确率提升，但 forbidden task 增加或 negation 下降，应回滚本次规则/语义扩展。
```

## 17. 运行说明

### 17.1 Docker 推荐启动

交付给他人联调时优先推荐 Docker。

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

检查：

```powershell
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/health
```

可选 frontend：

```powershell
docker compose --profile frontend up -d --build
```

停止：

```powershell
docker compose down
```

### 17.2 Windows 本地源码启动

创建配置：

```powershell
Copy-Item .env.local.example .env.local
```

安装后端：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
```

安装前端：

```powershell
npm.cmd --prefix frontend install
```

初始化 PostgreSQL：

```powershell
psql -U postgres -c "CREATE USER intent WITH PASSWORD 'intent';"
psql -U postgres -c "CREATE DATABASE intent_analysis OWNER intent;"
psql -U intent -d intent_analysis -f database/init/001_schema.sql
psql -U intent -d intent_analysis -f database/init/002_seed_data.sql
```

启动：

```powershell
.\scripts\start-local.ps1
```

只启动后端：

```powershell
.\scripts\start-local.ps1 -NoFrontend
```

停止：

```powershell
.\scripts\stop-local.ps1
```

### 17.3 测试命令

后端回归：

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest tests\backend -q -p no:cacheprovider
```

Context Provider 集成测试：

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest tests\backend\test_context_provider_integration.py -q -p no:cacheprovider
```

Benchmark validation：

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe evaluation\benchmark\benchmark_runner.py --split validation --semantic-mode local --llm-mode off
```

打包：

```powershell
.\scripts\create-handoff-package.ps1
```

打包 dry run：

```powershell
.\scripts\create-handoff-package.ps1 -DryRun
```

打包脚本会排除：

```text
.git/
.codex/
.agents/
.venv/
frontend/node_modules/
.runtime/
__pycache__/
.pytest_cache/
.env
.env.local
*.log
```

## 18. 当前验证状态

最近交付验证记录：

```text
Backend tests: 432 passed, 4 skipped
Docker Compose config: valid with .env.example
Package dry-run: passed
```

交付压缩包曾生成：

```text
dist/intent-analysis-engine-handoff-20260720-173426.zip
```

注意：如果代码继续变更，应重新运行测试和重新打包，不要默认旧压缩包代表最新状态。

## 19. 常见输入和预期行为

### 19.1 明确单任务

```text
输入：
生成销售报表

预期：
输出 DOCUMENT_GENERATE 或业务报表相关 task；
如果缺少报表范围、数据来源等必要输入，则 task-level clarification。
```

### 19.2 计算提成

```text
输入：
根据最新的提成政策计算销售提成

预期：
输出 RULE_CALCULATION_COMMISSION；
如果“最新提成政策”无法被上下文或外部系统明确解析，则要求补充 calculation_policy / calculation_basis 等字段。
```

### 19.3 多任务

```text
输入：
整理销售数据，分析下降原因，生成报告

预期：
输出三个 task；
若 L1 只识别“整理销售数据”，Partial Coverage Detector 应将剩余片段送 L3。
```

### 19.4 省略表达

```text
上下文：
上一轮任务是“计算2025年销售提成”

输入：
帮我再算一遍

预期：
识别为重新执行销售提成计算任务。
```

### 19.5 否定和未来规划

```text
输入：
以后希望自动提醒异常情况，但本次不考虑。

预期：
不能输出异常监控任务；
不能输出提醒任务。
```

### 19.6 信息不足

```text
输入：
帮我处理一下销售问题

预期：
不要强行加 L1/L2 规则；
应进入 L3 或返回 clarification_required=true。
```

## 20. 给 ChatGPT 的协作建议

如果把这份文档交给 ChatGPT，建议这样提问：

```text
你现在是这个 Intent Analysis Engine 项目的技术顾问。
请先阅读我提供的项目上下文文档。
之后回答问题时，请遵守：
1. 不要把本项目说成业务执行系统；
2. 不要假设 Context 模块由本项目实现；
3. 输出和接口以 TaskList schema 为准；
4. L1/L2 规则扩展必须由 benchmark validation 失败案例驱动；
5. blind_test 禁止用于规则开发；
6. 涉及流程执行时，只讨论 TaskList 如何交给流程执行引擎；
7. 涉及澄清时，优先使用 task-level clarification，而不是全局问题。
```

适合继续问的问题：

```text
请帮我检查 TaskList schema 是否适合流程执行引擎。
请帮我设计上下文模块的 HTTP 接口。
请帮我评估 L1/L2/L3 分层是否合理。
请帮我扩展 benchmark 样本，但不要污染 blind_test。
请帮我根据 validation failure_report 判断哪些 case 能加 L1 规则。
请帮我写流程执行引擎对接文档。
请帮我设计生产部署前检查清单。
```

## 21. 当前已知风险和后续建议

建议优先完善：

- Context Provider 从 mock 切换到真实外部服务时，需要明确 HTTP/gRPC 适配层、超时、重试、降级策略。
- 澄清会话当前应确认是否需要持久化到数据库，避免服务重启后丢失 session。
- 流程执行引擎需要明确 task_type 到真实执行器的映射关系。
- L3 大模型输出需要继续加强 schema validation、任务白名单校验、fallback 标识和审计日志。
- Benchmark 可以从 300 条扩展到 1000 条以上，并增加更多企业真实脱敏语料。
- 对否定、未来规划、跨句排除、上下文冲突的样本要持续补充。
- 前端演示和接口文档应保持同步，避免交付联调时出现字段理解偏差。
- 生产环境不要使用 mock provider 作为“看起来成功”的真实结果，fallback 必须显式暴露。

## 22. 关键原则总结

```text
Intent Analysis Engine = 意图理解 + 任务结构化
不是业务执行引擎
不是上下文管理系统
不是流程编排系统
不是文档生成系统
```

最重要的输出：

```text
标准 TaskList
```

最重要的工程约束：

```text
确定表达进 L1
语义近义进 L2
复杂/未覆盖片段进 L3
信息不足就澄清
未来规划/明确否定不能生成当前任务
每个 task 独立澄清
下游只执行 ready task
```
