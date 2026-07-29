# Intent Analysis Benchmark

This folder contains the production-style benchmark system for Intent Analysis Engine.

It is separate from development tests. Unit tests and rule development must not import or optimize against `datasets/blind_test`.

## Structure

```text
evaluation/benchmark/
├── benchmark_runner.py
├── build_seed_dataset.py
├── datasets/
│   ├── train/
│   ├── validation/
│   ├── blind_test/
│   └── manifest.json
└── metrics/

evaluation/error_analysis/
├── failure_classifier.py
└── report_generator.py
```

## Dataset Splits

| Split | Purpose |
| --- | --- |
| `train` | Threshold exploration, analysis, and controlled development. |
| `validation` | Regular benchmark during development and CI. |
| `blind_test` | Final acceptance only. Do not inspect or use for rules, prompts, thresholds, or model tuning. |

The v1 seed dataset contains 314 de-identified enterprise-style cases:

```text
train: 180
validation: 74
blind_test: 60
```

It is designed to expand to 1000+ cases by adding files under each split directory.

## Sample Format

```json
{
  "id": "BENCH-VALIDATION-001",
  "text": "用户原始输入",
  "intent_category": "short_instruction",
  "expected_tasks": [],
  "expected_task_types": [],
  "required_clarification": true,
  "missing_inputs": [],
  "forbidden_tasks": []
}
```

Optional fields supported by the runner:

```json
{
  "history": [{"role": "user", "text": "上一轮输入"}],
  "context": {
    "conversation_context": [],
    "project_context": [],
    "user_project_context": []
  },
  "expected_conflict_types": ["DATA_SOURCE_CONFLICT"],
  "expected_conflict_clarification": true,
  "expected_clarification_questions": ["请提供计算规则或适用政策。"],
  "max_extra_clarification_questions": 0,
  "clarification_answer": "使用2026规则，华东区域，ERP数据",
  "expected_recovery_status": "ready",
  "expected_recovery_missing_inputs": [],
  "expected_recovery_final_inputs": {
    "calculation_policy": "2026规则",
    "data_source": "ERP"
  }
}
```

## Commands

Validate validation split only:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe evaluation\benchmark\benchmark_runner.py --split validation --validate-only
```

Run validation benchmark:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe evaluation\benchmark\benchmark_runner.py --split validation --semantic-mode local --llm-mode off --output evaluation\benchmark\validation_report.json
```

The runner writes a failure report by default:

```text
evaluation/error_analysis/failure_report.json
```

Generate an explicit before/after optimization report:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe evaluation\error_analysis\report_generator.py `
  --benchmark-report evaluation\benchmark\validation_report_after.json `
  --split validation `
  --output evaluation\error_analysis\failure_report_after.json `
  --before-report evaluation\benchmark\validation_report_before.json `
  --after-report evaluation\benchmark\validation_report_after.json `
  --optimization-output evaluation\error_analysis\optimization_report.json `
  --added-rule-count 0 `
  --added-semantic-example-count 2
```

Run final blind benchmark:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe evaluation\benchmark\benchmark_runner.py --split blind_test --allow-blind-test --semantic-mode local --llm-mode off --output evaluation\benchmark\blind_test_report.json
```

Analyze sealed blind context recovery failures without using blind cases for rule development:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe evaluation\error_analysis\context_recovery_analysis.py `
  --benchmark-report evaluation\benchmark\blind_test_report_context_recovery_final.json `
  --split blind_test `
  --allow-blind-test
```

The analysis redacts raw blind text and writes:

```text
evaluation/error_analysis/context_recovery_analysis_report.json
evaluation/error_analysis/context_distribution_report.json
```

Regenerate v1 seed data:

```powershell
.\.venv\Scripts\python.exe evaluation\benchmark\build_seed_dataset.py
```

## Metrics

The runner reports:

- task type exact accuracy
- task count accuracy
- clarification accuracy
- clarification decision accuracy
- clarification field accuracy
- clarification question accuracy
- no unnecessary clarification question accuracy
- clarification recovery accuracy
- missing input accuracy
- forbidden task pass rate
- future scope false positive rate
- negation false positive rate
- macro precision / recall / F1 over task types
- by-split summary
- by-intent-category summary
- failed case details
- conflict detection accuracy
- conflict clarification accuracy
- false resolution rate

Failure reports classify failures as:

- `L1_RULE_MISS`
- `L2_SEMANTIC_MISS`
- `NEED_L3_OR_CLARIFICATION`

Only `L1_RULE_MISS` and `L2_SEMANTIC_MISS` may drive L1/L2 expansion. Protected future-scope, negation, ambiguity, context-resolution, and missing-input failures must not be converted into broad positive rules.
