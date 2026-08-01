# 脱敏真实场景验证

本项目不连接生产系统，也不使用真实个人或企业数据。所有场景样例均是可版本控制的脱敏/仿真数据。

| 场景 | 样例文件 | 验证结果 |
| --- | --- | --- |
| 制造业财务经营分析 | `tests/fixtures/financial_statement_anonymized.json` | 趋势、同比、环比、杜邦分解、异常检测及来源溯源。 |
| 制造业原料价格预测 | `tests/fixtures/material_price_anonymized.json` | 历史窗口、波动趋势、确定性线性预测、区间与决策参考标记。 |
| 法律服务经营核算 | `tests/fixtures/law_firm_metrics_anonymized.json` | 净利润、成本占比、目标对比和超标候选项。 |

## 运行方式

```bash
python -m pytest -q
PYTHONPATH=src python -m uvicorn analysis_prediction_engine.main:app --host 127.0.0.1 --port 8000
```

运行服务后，向 `POST /v1/analysis-jobs/evaluate` 提交任一样例 JSON。调用方负责认证、权限校验、审计留痕、任务编排、数据归集、报告撰写与通知推送。

## 质量限制

- 数值计算使用确定性工具和 `Decimal`；不通过 LLM 完成算术；HTTP 中的十进制数以字符串传输，避免浮点精度丢失。
- 输入记录为不可变模型；响应中的关键数值携带来源记录/字段/期间/公式版本。多输入计算会为每个输入生成独立的来源引用。
- 引擎只生成 `alert_candidates`，不发送通知；不写外部系统；全部结果均为人工确认前的决策参考，不代替真人决策。
- 接入正式平台前，须将统一追踪 ID、鉴权上下文、异步受理格式及上下游 schema 与已拍板的 L2 规范对齐。
