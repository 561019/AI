# Long Context Task Extraction Layer

更新时间：2026-07-13

## 1. 目标与边界

Long Context Task Extraction Layer 负责从长文本中发现明确任务，把任务候选逐个交给现有 Intent Analysis Engine。它不执行业务任务，不补全业务数据，不改变 `IntentAnalysisResult` / TaskList 对外契约。

核心判断原则：

- 背景说明不是任务。
- 只提到业务对象不是任务。
- 只有明确的动作与对象组合才能形成任务候选。
- 用户明确建立的先后关系可以形成任务依赖，但不能补造前序任务的业务结果。
- 每个候选仍必须经过 Rule Matcher、Semantic Matcher、Task Builder 和 Input Validator。

## 2. 模块

```text
backend/app/services/task_extraction/
├── long_text_parser.py
├── task_segmenter.py
├── intent_extractor.py
└── task_merger.py
```

- `LongTextParser`：按句子边界分块，保存字符偏移；无标点超长段落使用受控硬切分。
- `TaskSegmenter`：区分背景、目标、动作、约束和补充说明。
- `IntentExtractor`：识别显式动作与业务对象，生成 `TaskCandidate`。
- `TaskMerger`：去除重叠块重复候选，合并同义重复表达，并推导直接依赖。

## 3. 处理流程

```text
原始文本
  -> 长度与句子数判断
  -> 句子边界分块（默认 2000 字符，重叠 200 字符）
  -> 语义片段分类
  -> 显式动作 + 业务对象候选发现
  -> 跨块去重、同义合并、依赖推导
  -> 每个候选进入现有 StandardIntentAnalyzer
       -> Level1 Rule Matcher
       -> Level2 Semantic Matcher (BGE)
       -> Level3 LLM fallback
       -> Task Builder
       -> Input Validator
  -> 任务合并和最终 Input Validator
  -> 标准 IntentAnalysisResult
```

长文本提取在以下任一条件满足时启用：

- 文本长度至少 120 字符。
- 文本包含至少 3 个完整句子。

短文本继续使用原有对话理解路径。

## 4. 分块策略

长度分类：

```text
short:  < 1000 字符
medium: 1000-10000 字符
long:   > 10000 字符
```

默认配置：

```env
LONG_TEXT_CHUNK_SIZE=2000
LONG_TEXT_CHUNK_OVERLAP=200
LONG_TEXT_ACTIVATION_LENGTH=120
LONG_TEXT_ACTIVATION_SENTENCES=3
```

重叠窗口用于保留块边界语义，候选通过字符偏移和语义指纹去重。处理时间和内存随输入长度近似线性增长。

## 5. 动作和边界

当前显式动作覆盖：

```text
查询、获取、整理、统计、计算、分析、比较、生成、预测、
检查、转换、导出、同步、解析、提取、筛选、排序、监控、发起、办理
```

以下表达不会单独形成任务：

```text
销售数据下降
客户信息
项目启动以来
我已经整理了资料
不需要重复处理
```

以下表达会形成任务：

```text
分析销售数据下降原因
从 CRM 获取客户信息
筛选逾期超过三十天的客户
根据现行政策计算销售提成
计算后再生成计提凭证
```

## 6. 输出和调试

对外响应仍使用现有字段：

```json
{
  "tasks": [
    {
      "task_id": "",
      "task_name": "",
      "task_type": "",
      "engine_code": "",
      "required_inputs": [],
      "missing_inputs": [],
      "dependencies": []
    }
  ],
  "clarification_required": false
}
```

用户要求中的 `description` 由现有 `task_name` 表达，未新增对外字段。`debug=true` 时增加 `long_context_extraction`，包含文档分块、语义片段、原始候选、合并候选、背景片段和约束片段。

## 7. 评测

数据集：`evaluation/long_text_dataset.json`

- 共 100 条。
- 业务邮件、会议纪要、用户需求描述、聊天记录、大量背景文本各 20 条。
- 每条包含 `expected_actions`、`expected_tasks`、`expected_engine` 和 `should_clarify`。

运行：

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe long_text_evaluation_runner.py --semantic-mode local --llm-mode off --output evaluation\long_text_report.json
```

2026-07-13 结果：

```text
100/100 完全通过
候选召回率       100%
任务拆解准确率   100%
task_type准确率  100%
engine准确率     100%
clarification准确率 100%
```

完整后端回归：`376 passed, 4 skipped`。原复杂对话评测保持 `100/100`。

未被确定性候选覆盖的片段现在会进入受控隐式语义兜底，详细设计见 `docs/development/SEMANTIC_SAFETY_FALLBACK.md`。

## 8. 容量

API schema 当前没有 `max_length`，抽取器也没有应用级字符硬上限。容量测试已验证：

```text
20,000 字符：通过
50,000 字符：通过
100,000 字符：通过
```

三档测试均在文本开头、中间和结尾放置任务，全部保留。当前可对外表述为“已验证支持 100,000 字符”；更大文本尚未做正式容量和并发基准，不能表述为无限支持。

## 9. 首轮失败和修复

首轮评测为 `41/100`，主要失败类型：

- “会议形成的行动项”中的“形成”抢占实际请求动作。
- “项目启动以来”被错误识别为发起流程。
- “根据规则计算”和“设置每天提醒”等约束前置表达漏识别。
- 从 CRM/ERP 获取数据时，归一化丢失来源系统。
- “逾期超过三十天的客户”被阈值关键词误判为监控任务。
- 长文本背景中的早期对象遮蔽后文明确的销售数据来源。

修复后100条无失败案例。剩余风险主要来自未覆盖的新动作说法、复杂否定、跨段隐含依赖和极大文本并发资源占用；这些情况应继续通过真实失败语料扩充回归集。
