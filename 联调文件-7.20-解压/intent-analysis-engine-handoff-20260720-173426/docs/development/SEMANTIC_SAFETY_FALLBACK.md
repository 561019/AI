# Semantic Safety Fallback

更新时间：2026-07-13

## 1. 目标

本阶段补足四项能力：

1. 长文本未覆盖片段的语义任务兜底。
2. Level3 LLM结果的Function Registry强校验。
3. 每个LLM任务的原文证据校验。
4. 未知、低置信度或不可信结果的安全拒绝。

外部 `IntentAnalysisResult` / TaskList 契约没有增加字段。`evidence_span`只存在于内部模型协议和 `debug=true` 响应中。

## 2. 新处理路径

```text
长文本分块
  -> 确定性Task Candidate抽取
  -> 根据字符范围找出未覆盖片段
  -> 每批最多8000字符调用Implicit Task Fallback
  -> 校验证据片段和置信度
  -> 与确定性候选按原文位置合并
  -> 每个候选进入现有StandardIntentAnalyzer
       -> Rule
       -> BGE
       -> Level3 LLM
       -> Registry + Evidence Validation
       -> Input Validator
  -> TaskList
```

模型不可用不会中断正常路径。未覆盖片段没有产生可信候选时，系统保留已识别任务；整篇没有任务时返回空任务澄清。

## 3. 内部LLM证据协议

Level3必须返回：

```json
{
  "result": {
    "tasks": []
  },
  "evidence_spans": [
    {
      "task_index": 0,
      "evidence_span": "用户原文中的连续片段"
    }
  ]
}
```

要求：

- 每个任务有且只有一个证据片段。
- `task_index`必须完整覆盖任务列表。
- `evidence_span`必须是输入原文中的连续子串。
- 证据不得写入对外TaskList字段。
- 无任务或不支持请求必须返回空任务和澄清。

## 4. Registry校验

Level3任务进入TaskList前依次检查：

- `task_type`存在于Function Registry。
- `engine_code`等于该任务类型注册的引擎编码。
- `target_engine`等于注册引擎名称。
- 任务依赖只引用当前结果中的任务ID。
- 任务不能依赖自身。
- `overall_confidence`不低于配置阈值。

任意任务失败时拒绝整个Level3任务列表，避免部分可信、部分伪造的结果混合输出。

## 5. 安全拒绝

以下情况统一返回：

```json
{
  "tasks": [],
  "clarification_required": true
}
```

- 未注册任务类型。
- 引擎编码或名称与注册表不一致。
- 缺少证据、证据数量错误或证据不在原文。
- LLM置信度低于阈值。
- 依赖不存在或自依赖。
- 请求不属于任何注册能力。
- 模型不可用或响应格式无效。

正常API不暴露内部拒绝细节。`debug=true`时可查看：

```text
implicit_task_fallback
level3_result.validation.accepted
level3_result.validation.rejection_reasons
final_decision
```

## 6. 配置

```env
LLM_CONFIDENCE_THRESHOLD=0.70
IMPLICIT_TASK_CONFIDENCE_THRESHOLD=0.70
IMPLICIT_FALLBACK_BATCH_CHARACTERS=8000
```

阈值应由独立盲测集校准，不应仅凭经验长期固定。

## 7. 验证

新增测试：`tests/backend/test_semantic_safety_fallback.py`

覆盖：

- 模板外隐式长文本抽取。
- 显式任务与隐式任务混合。
- 合法注册任务和原文证据通过。
- 未注册task_type拒绝。
- engine映射错误拒绝。
- 缺失或伪造证据拒绝。
- 不支持能力返回空任务澄清。
- 隐式候选证据不可信时拒绝。

2026-07-13验证结果：

```text
后端：376 passed, 4 skipped
长文本评测：100/100
复杂对话评测：100/100
Compose配置：通过
本地兼容模型未知请求：0 tasks + clarification
本地兼容模型隐式请求：2 candidates + exact evidence
```

## 8. 当前限制

- 隐式任务质量取决于实际LLM，不应把本地兼容服务结果视为真实模型效果。
- 未覆盖片段按最多8000字符批处理，极长文本会产生多次模型调用。
- BGE高置信度但语义错误的候选会在Level2直接通过，不进入Level3证据校验；需要用盲测数据继续校准阈值和增加拒绝区间。
- 当前安全日志只在debug中提供，尚未建立独立的未知语义人工审核队列。
