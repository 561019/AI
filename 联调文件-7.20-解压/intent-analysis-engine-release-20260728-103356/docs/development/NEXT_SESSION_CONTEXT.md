# Intent Analysis Engine - Next Session Context

更新时间：2026-07-22  
工作区：`D:\AIProjects\intent-analysis-engine`  
用途：新会话开始时优先加载本文件，用于快速恢复项目边界、关键决策、已完成能力、待办事项、重要文件和当前评测状态。

---

## 1. 当前结论

本项目已经具备企业级意图分析引擎的核心架构雏形，适合作为 **联调版 / POC / 内部试运行版本**。

当前不建议直接承诺生产级上线，主要原因是：

- blind_test 总体 full-pass 偏低：`24/60 = 40.00%`
- blind_test 上下文恢复弱：`context_recovery_pass_rate = 0.00%`
- 真实泛化中主要问题集中在上下文省略表达恢复、误匹配覆盖、澄清字段过问
- 当前 validation 指标较好，但 blind_test 证明仍需要真实脱敏语料和封闭验收继续打磨

下一阶段最重要目标：**基于 validation 抽象失败样本修复上下文恢复与澄清精度，不使用 blind_test case 直接开发规则。**

---

## 2. 项目职责边界

Intent Analysis Engine 只负责：

- 意图理解
- 参数抽取
- 上下文调用与消费
- 多任务拆解
- 否定 / 未来规划过滤
- 冲突检测与处理
- task-level clarification
- 输出标准 TaskList 给流程执行引擎

Intent Analysis Engine 不负责：

- 不开发 Context & Prompt Management
- 不存储或维护外部上下文系统
- 不执行业务流程
- 不查询真实 ERP / CRM / 数据库
- 不生成真实报表正文、凭证、邮件、审批流结果
- 不修改流程执行引擎接口
- 不把 Function Registry 当作执行路由表

核心边界：

```text
用户输入
  -> Context Provider 外部依赖
  -> Intent Analysis Engine
  -> TaskList
  -> Flow Execution Engine
```

---

## 3. 不可破坏的关键决策

### 3.1 TaskList 是最终对外契约

禁止修改 TaskList 整体结构。当前任务项需要保持：

```json
{
  "task_id": "",
  "task_type": "",
  "task_description": "",
  "action": "",
  "object": "",
  "required_inputs": [],
  "missing_inputs": [],
  "clarification_required": false,
  "clarification_questions": [],
  "dependencies": [],
  "status": "",
  "conflicts": [],
  "confidence": 0.0
}
```

兼容字段：

- `global_clarification_required`
- `clarification_required`
- `clarification_questions`

规则：任意 task 需要澄清，则 `global_clarification_required=true`。

### 3.2 Context Provider 是外部依赖

Engine 只调用和消费 context，不开发 Context 系统本体。

当前接口约定：

```python
get_context(user_id, conversation_id, project_id)
```

返回：

```json
{
  "conversation_context": [],
  "project_context": [],
  "user_project_context": []
}
```

统一输入格式：

```json
{
  "user_input": "...",
  "context": {
    "current_conversation": {},
    "current_project": {},
    "historical_projects": {}
  }
}
```

上下文优先级：

```text
current_input
> conversation_context
> project_context
> historical_projects
```

### 3.3 blind_test 封闭

blind_test 只用于最终验收。

禁止：

- 把 blind_test case 加入 validation / train
- 根据单个 blind case 增加关键词规则
- 直接用 blind 原句调 L1/L2 / prompt / threshold

允许：

- 统计 blind 失败类型
- 生成红acted报告
- 从失败类型抽象出 validation 样本
- 在 validation 上完成下一轮开发和验证

### 3.4 L1/L2 扩展必须由 validation 失败驱动

不能凭经验直接加规则。

失败分类原则：

- `L1_RULE_MISS`：高确定表达且规则未命中，只能增加窄规则
- `L2_SEMANTIC_MISS`：同义、口语、业务近义表达，扩展 semantic examples / descriptions
- `NEED_L3_OR_CLARIFICATION`：歧义、信息不足、protected case，不加 L1/L2

### 3.5 L3 / LLM 只能兜底理解，不能伪装执行

Model Gateway fallback 到 mock 时，mock 必须显式：

```json
{
  "fallback": true,
  "provider": "mock"
}
```

禁止 mock 伪装成真实模型结果。

Debug 日志允许记录：

- provider
- model
- request_id
- 耗时
- retry 次数
- fallback 状态

禁止记录：

- API_KEY
- 任何密钥

---

## 4. 整体架构思路

```text
HTTP API / User Input
  -> Conversation Understanding
     - 历史对话
     - 指代消解
     - 噪声过滤
     - 口语归一化
     - Context Provider 调用
     - 上下文省略表达恢复

  -> Task Segmenter
     - 短文本 / 长文本分段
     - 多任务切分
     - 候选 segment 绑定

  -> L1 Rule Matching
     - 高确定规则
     - 不扩大模糊关键词

  -> L2 Semantic Matching
     - BGE / local semantic runtime
     - semantic examples / descriptions

  -> Partial Coverage Detector
     - 只把 uncovered_segments 送 L3
     - 不整句调用 LLM

  -> L3 LLM Fallback
     - Model Gateway
     - retry / timeout / fallback
     - LLM Response Contract Validator

  -> Task Merge
     - candidate merge 前过滤 future_scope / negation
     - dependency merge
     - conflict detection / resolution

  -> Task-level Input Validator
     - required_inputs
     - missing_inputs
     - task-level clarification
     - dependency waiting

  -> Final TaskList
```

---

## 5. 已完成能力

### 5.1 Task Extraction 增强

已完成：

- 长文本任务抽取
- 多任务拆分
- 全局否定解析
- 后置否定覆盖前文候选任务
- Future Scope Filter
- candidate merge 前过滤无效任务
- 多任务场景只过滤被否定部分

覆盖表达：

- 未来规划
- 以后
- 后续
- 未来考虑
- 暂不需要
- 目前不包含
- 本次不做
- 不考虑

关键文件：

- `backend/app/services/task_extraction/future_scope_filter.py`
- `backend/app/services/task_extraction/global_negation_resolver.py`
- `backend/app/services/task_extraction/intent_extractor.py`
- `backend/app/services/task_extraction/task_consolidator.py`
- `backend/app/services/task_extraction/task_merger.py`
- `evaluation/benchmark/datasets/validation/validation_scope_negation_v1.jsonl`

### 5.2 Model Gateway 生产稳定性

已完成：

- `.env` 支持 `LLM_TIMEOUT_SECONDS=120`
- 默认超时 120 秒
- 最大 3 次 retry
- backoff：`2s / 5s / 10s`
- debug 日志记录 provider / model / request_id / elapsed / retry / fallback
- DeepSeek 失败 fallback 到 mock provider
- mock fallback 显式标记 `fallback=true`、`provider=mock`

关键文件：

- `backend/app/services/model_gateway/gateway.py`
- `backend/app/services/model_gateway/model_router.py`
- `backend/app/services/model_gateway/providers/deepseek_provider.py`
- `backend/app/services/model_gateway/providers/mock_provider.py`
- `backend/app/services/model_gateway/schemas/llm_response.py`
- `tests/backend/test_model_gateway.py`
- `tests/backend/test_llm_model_gateway.py`

### 5.3 Context Provider 接入

已完成：

- 新增 Context Provider 模块
- Mock Context Provider
- Context 输入格式统一
- Conversation Understanding 中接入外部 context
- 支持省略表达恢复

关键文件：

- `backend/app/services/context_provider/base.py`
- `backend/app/services/context_provider/client.py`
- `backend/app/services/context_provider/schemas.py`
- `backend/app/services/context_provider/mock_provider.py`
- `backend/app/services/conversation_understanding/conversation_parser.py`
- `tests/backend/test_context_provider_integration.py`
- `tests/backend/test_context_recovery.py`

当前已支持的省略表达方向：

- 再算一遍
- 重新计算
- 接着改
- 换个维度看看
- 继续分析
- 按刚才的方式处理

### 5.4 Partial Coverage Detector

已完成：

- L1/L2 只命中部分任务时，剩余 uncovered segments 可进入 L3
- 不整句调用 LLM
- 已识别 task 绑定原文 segment
- debug 输出覆盖率、未覆盖片段、llm_called

关键文件：

- `backend/app/services/intent_analysis_engine/partial_coverage_detector.py`
- `tests/backend/test_partial_coverage_detector.py`

输出示例：

```json
{
  "l1_tasks": [],
  "l2_tasks": [],
  "coverage_rate": 0.7,
  "uncovered_segments": [],
  "llm_called": true
}
```

### 5.5 Task-level Clarification

已完成：

- 从 global clarification 改为 task-level clarification
- 每个 task 独立维护 missing_inputs / clarification_questions / status
- 禁止不同 task 的 missing_inputs 混合
- dependency 缺输入时，后续任务进入 `waiting_dependency`

关键文件：

- `backend/app/services/intent_analysis_engine/input_validator.py`
- `backend/app/services/intent_analysis_engine/clarification/session_manager.py`
- `backend/app/services/intent_analysis_engine/clarification/answer_mapper.py`
- `backend/app/services/intent_analysis_engine/clarification/clarification_state.py`
- `tests/backend/test_clarification_session.py`

### 5.6 Clarification Session 恢复

已完成：

- 首次识别缺信息 -> 创建 ClarificationSession
- 用户补充 -> 不重新生成 task
- answer mapper 回填原 task missing_inputs
- 重新校验 task 状态
- 保持原 task_id

API：

```http
POST /api/v1/intent/clarification/answer
```

请求：

```json
{
  "clarification_session_id": "CS001",
  "answer": "使用2026销售提成规则，计算华东区域，数据来自ERP"
}
```

响应：

```json
{
  "task_id": "T001",
  "status": "ready",
  "missing_inputs": [],
  "final_inputs": {
    "calculation_policy": "2026销售提成规则",
    "data_scope": "华东区域",
    "data_source": "ERP"
  }
}
```

### 5.7 Conflict Resolution

已完成 5 类企业级冲突：

- `DATA_SOURCE_CONFLICT`
- `TIME_RANGE_CONFLICT`
- `STATISTICAL_DEFINITION_CONFLICT`
- `CURRENT_CONTEXT_CONFLICT`
- `PROJECT_USER_CONTEXT_CONFLICT`

关键策略：

- 当前输入优先，但需要记录 conflict
- 两个明确数据源、时间范围、统计口径冲突时，不自动合并，进入 clarification
- project context 优先于 historical_projects，但记录 conflict

关键文件：

- `backend/app/services/intent_analysis_engine/conflict/detector.py`
- `backend/app/services/intent_analysis_engine/conflict/resolver.py`
- `backend/app/services/intent_analysis_engine/conflict/rules.py`
- `backend/app/services/intent_analysis_engine/conflict/schemas.py`
- `tests/backend/test_conflict_resolution.py`
- `evaluation/benchmark/datasets/validation/validation_conflict_v1.jsonl`

### 5.8 Benchmark / Error Analysis 体系

已完成：

- `train / validation / blind_test` 数据隔离
- 至少 300 条样本体系，可扩展到 1000+
- benchmark runner
- metrics 聚合
- failure_report
- before / after optimization report
- conflict metrics
- clarification 细分指标
- context recovery blind failure 分析

关键文件：

- `evaluation/benchmark/benchmark_runner.py`
- `evaluation/benchmark/metrics/tasklist_metrics.py`
- `evaluation/error_analysis/failure_classifier.py`
- `evaluation/error_analysis/report_generator.py`
- `evaluation/error_analysis/context_recovery_analysis.py`
- `evaluation/benchmark/datasets/manifest.json`

当前数据集规模：

```text
train: 180
validation: 80
blind_test: 60
total: 320
```

---

## 6. 当前评测状态

### 6.1 validation 当前基线

报告：

- `evaluation/benchmark/validation_report_context_recovery_abstract_current.json`
- `evaluation/error_analysis/failure_report_context_recovery_abstract_current.json`

指标：

```text
total: 80
passed: 58
task_type_exact_accuracy: 87.50%
task_count_accuracy: 93.75%
clarification_accuracy: 82.50%
clarification_field_accuracy: 76.25%
clarification_question_accuracy: 100.00%
clarification_recovery_accuracy: 100.00%
context_recovery_accuracy: 77.78%
false_positive_rate: 0.00%
future_scope_false_positive_rate: 0.00%
negation_false_positive_rate: 0.00%
macro_recall: 89.58%
macro_f1: 88.96%
conflict_detection_accuracy: 100.00%
conflict_clarification_accuracy: 100.00%
false_resolution_rate: 0.00%
```

新增抽象 context validation 中仍失败的样本：

- `BENCH-VALIDATION-CONTEXT-ABSTRACT-002`
- `BENCH-VALIDATION-CONTEXT-ABSTRACT-003`
- `BENCH-VALIDATION-CONTEXT-ABSTRACT-004`
- `BENCH-VALIDATION-CONTEXT-ABSTRACT-006`

主要失败形态：

- task_type 正确但恢复后多问参数
- 上下文存在但省略表达未绑定最近 task
- workflow follow-up 缺失字段多问 `operation`
- conversation 优先级恢复后仍触发不必要 clarification

### 6.2 blind_test 封闭验收结果

报告：

- `evaluation/benchmark/blind_test_report_context_recovery_final.json`
- `evaluation/error_analysis/context_recovery_analysis_report.json`
- `evaluation/error_analysis/context_distribution_report.json`

指标：

```text
total: 60
passed: 24
overall_full_pass: 40.00%
context_related_total: 12
context_related_passed: 1
context_related_failed: 11
context_related_pass_rate: 8.33%
context_dependency_total: 6
context_dependency_passed: 0
context_recovery_pass_rate: 0.00%
```

blind 上下文失败分类：

```text
CONTEXT_MATCH_ERROR: 9
ELLIPSIS_PARSE_ERROR: 2
CONTEXT_NOT_FOUND: 0
CONTEXT_PRIORITY_ERROR: 0
CONTEXT_CONFLICT_ERROR: 0
CLARIFICATION_MISSING: 0
```

结论：

- Context Provider 有返回，不是上下文没取到
- 主要问题是存在上下文但没有正确匹配最近 task
- 当前短表达的 L1/L2 弱匹配会覆盖上下文恢复
- 需要在 validation 抽象样本上修复，不得直接使用 blind 原句

---

## 7. 重要文件修改记录

| 文件 / 目录 | 当前职责 |
| --- | --- |
| `backend/app/services/context_provider/` | 外部 Context Provider 接口、schema、mock provider |
| `backend/app/services/conversation_understanding/conversation_parser.py` | 上下文调用、省略表达恢复、对话理解主流程 |
| `backend/app/services/intent_analysis_engine/analyzer.py` | L1/L2/L3 主分析链路 |
| `backend/app/services/intent_analysis_engine/input_validator.py` | task-level required_inputs、missing_inputs、clarification |
| `backend/app/services/intent_analysis_engine/partial_coverage_detector.py` | 部分覆盖检测，uncovered segments 送 L3 |
| `backend/app/services/intent_analysis_engine/conflict/` | 企业级冲突检测与解决 |
| `backend/app/services/intent_analysis_engine/clarification/` | ClarificationSession、answer mapper、状态恢复 |
| `backend/app/services/task_extraction/future_scope_filter.py` | 未来规划、暂不做、本次不包含过滤 |
| `backend/app/services/task_extraction/global_negation_resolver.py` | 跨句否定、后置否定处理 |
| `backend/app/services/task_extraction/intent_extractor.py` | 长文本任务候选抽取 |
| `backend/app/services/model_gateway/` | LLM provider、timeout、retry、fallback、日志 |
| `backend/app/services/model_gateway/contract_validator.py` | LLM 输出契约校验 |
| `backend/app/config/semantic_capabilities.yaml` | L2 semantic capabilities、examples、required inputs |
| `evaluation/benchmark/benchmark_runner.py` | benchmark 运行器 |
| `evaluation/benchmark/metrics/tasklist_metrics.py` | task / clarification / conflict / context metrics |
| `evaluation/error_analysis/failure_classifier.py` | validation 失败分类 |
| `evaluation/error_analysis/report_generator.py` | failure report 和 before/after report |
| `evaluation/error_analysis/context_recovery_analysis.py` | blind context failure 红acted分析 |
| `evaluation/benchmark/datasets/validation/validation_context_recovery_abstract_v1.jsonl` | 从 blind 失败类型抽象出的 validation 样本 |
| `evaluation/benchmark/datasets/validation/validation_scope_negation_v1.jsonl` | future_scope / negation validation |
| `evaluation/benchmark/datasets/validation/validation_conflict_v1.jsonl` | conflict validation |
| `evaluation/benchmark/datasets/validation/validation_clarification_v1.jsonl` | clarification 细分评测 |
| `docs/development/EXTERNAL_CONTEXT_CONTRACT.md` | 外部 Context 模块接口约定 |
| `docs/api/INTENT_ANALYSIS_API.md` | API 文档 |
| `README.md` | 项目总说明 |

---

## 8. 常用验证命令

### 8.1 单测

```powershell
cd D:\AIProjects\intent-analysis-engine
.\.venv\Scripts\python.exe -m pytest tests\backend\test_context_recovery.py tests\backend\test_error_analysis.py -q
```

最近结果：

```text
11 passed
```

### 8.2 validation 数据校验

```powershell
.\.venv\Scripts\python.exe evaluation\benchmark\benchmark_runner.py `
  --split validation `
  --validate-only `
  --output evaluation\benchmark\dataset_validation_report.json
```

最近结果：

```text
Benchmark dataset validation: 80 cases
IDs unique: True
```

### 8.3 validation benchmark

```powershell
.\.venv\Scripts\python.exe evaluation\benchmark\benchmark_runner.py `
  --split validation `
  --semantic-mode local `
  --llm-mode off `
  --output evaluation\benchmark\validation_report_context_recovery_abstract_current.json `
  --failure-report evaluation\error_analysis\failure_report_context_recovery_abstract_current.json
```

### 8.4 blind context failure 分析

仅封闭分析使用，不能用于规则开发：

```powershell
.\.venv\Scripts\python.exe evaluation\error_analysis\context_recovery_analysis.py `
  --benchmark-report evaluation\benchmark\blind_test_report_context_recovery_final.json `
  --split blind_test `
  --allow-blind-test
```

保护校验：

```powershell
.\.venv\Scripts\python.exe evaluation\error_analysis\context_recovery_analysis.py --split blind_test
```

期望失败：

```text
blind_test is protected. Re-run with --allow-blind-test for sealed analysis reporting only.
```

---

## 9. 当前待办事项

### P0 - 下一轮必须优先处理

1. 修复上下文恢复误匹配
   - 目标：上下文存在时，最近相关 task identity 应优先于当前短表达弱匹配
   - 驱动数据：`validation_context_recovery_abstract_v1.jsonl`
   - 禁止：使用 blind 原句新增规则

2. 收敛恢复后的 missing_inputs
   - 已恢复 task_type 时，不应继续多问 `operation`、`analysis_object`、`process_name` 等已由上下文提供的字段
   - 重点文件：`conversation_parser.py`、`input_validator.py`

3. 保持无上下文省略表达进入 clarification
   - 禁止无依据从历史项目生成当前未请求任务

4. 每次修改后必须跑 validation benchmark
   - 对比 `context_recovery_accuracy`
   - 对比 `clarification_accuracy`
   - 对比 `false_positive_rate`
   - 对比 future_scope / negation false positive

### P1 - 企业级质量提升

1. 把真实脱敏企业语料扩展到 1000+ 条
2. 为 L1/L2 增加变更审批和 benchmark gate
3. 增加 CI 阈值：
   - validation task_type accuracy >= 90%
   - validation context recovery >= 90%
   - false_positive_rate <= 1%
   - negation / future_scope false positive 接近 0
4. 为 API 增加 schema version / TaskList version
5. 完善 request_id 链路追踪
6. 增加线上 feedback 回流机制
7. 增加租户隔离、脱敏、审计日志策略

### P2 - 联调与交付

1. 冻结 integration-preview 版本
2. 确认 Context Provider 接口与外部模块对齐
3. 确认 Flow Execution Engine 接收 TaskList 的接口契约
4. 补充联调 mock 数据
5. 确保压缩包包含：
   - README
   - 启动说明
   - API 文档
   - mock 数据
   - benchmark 报告
   - 测试截图或报告

---

## 10. 推荐下一步执行顺序

下一次新会话建议从这里开始：

1. 读取本文件
2. 读取：
   - `evaluation/error_analysis/context_recovery_analysis_report.json`
   - `evaluation/benchmark/datasets/validation/validation_context_recovery_abstract_v1.jsonl`
   - `backend/app/services/conversation_understanding/conversation_parser.py`
   - `backend/app/services/intent_analysis_engine/input_validator.py`
3. 先跑当前 validation benchmark，确认基线
4. 只针对 validation 抽象失败修复 context recovery
5. 跑 validation before/after
6. 如果 validation 明显提升且 false positive 不上升，再做最终 blind sealed acceptance

---

## 11. 企业级上线判断

当前状态：

```text
适合：联调版 / POC / 内部试运行
不适合：直接生产级上线承诺
```

生产级建议门槛：

```text
validation task_type accuracy >= 90%
validation context recovery >= 90%
blind full-pass >= 75%
false_positive_rate <= 1%
future_scope_false_positive_rate ~= 0
negation_false_positive_rate ~= 0
clarification_decision_accuracy >= 90%
clarification_field_accuracy >= 90%
```

当前最大风险：

- 上下文恢复泛化不足
- 澄清字段过问
- blind_test 真实泛化仍弱

当前最大优势：

- 职责边界清晰
- TaskList 契约稳定
- L1/L2/L3 分层清楚
- Context Provider 外部依赖边界正确
- conflict / clarification / benchmark 体系已经建立
- 已具备继续工程化打磨的基础
