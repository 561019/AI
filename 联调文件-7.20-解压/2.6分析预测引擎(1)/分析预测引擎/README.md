# 分析预测引擎

面向企业 AI 平台 L2 层的**内部同步分析计算接口**。它只消费上游已完成归集的脱敏/业务数据，输出可供后续内容产出、监控提醒或人工决策流程消费的结构化分析结论；不承担意图解析、数据归集、报告撰写、通知推送、外部写入或自主经营决策。

## 能力与边界

- **财务经营分析**：趋势、同比、环比、杜邦分解与异常识别。
- **原料价格预测**：对连续月度历史价格进行确定性线性趋势预测，返回历史窗口、预测区间、模型版本和不确定性说明。
- **经营指标分析**：净利润、成本占比、目标对比和 `alert_candidates`；候选项由监控提醒引擎决定是否推送。
- 所有数值计算使用确定性 `Decimal` 工具；HTTP 响应中的十进制数使用字符串以保留精度。
- 所有结果均具有 `decision_reference_only: true`、`human_confirmation_required: true` 和 `effective: false`；结果不会自动生效或代替真人决策。
- 输入必须是上游已归集数据。调用方负责认证授权、审计留痕、任务编排、异步受理/结果通知、数据归集、报告生成与外部系统写入。

## 安装与运行

要求 Python 3.12 或更高版本：

```bash
python -m pip install -e ".[test]"
PYTHONPATH=src python -m uvicorn analysis_prediction_engine.main:app --host 127.0.0.1 --port 8000
```

- `GET /health` 返回服务状态。
- `POST /v1/analysis-jobs/evaluate` 接受 `schema_version: "v1"` 和以下 `analysis_type`：`financial_statement`、`price_forecast`、`business_metric`。
- 每一个成功或可识别的校验错误都保留调用方的 `trace_id`；所有数值由字符串表示。

运行全部验证：

```bash
python -m pytest -q
```

## 平台集成说明

本仓库实现的是分析预测引擎的同步计算核心。需求中财务与价格场景的“受理回执、异步执行、通知送达”由 L2 流程管控和通知通道负责；本接口不会创建任务、持久化状态或发送通知。接入正式平台前，须与已拍板的 L2 层间交互、统一追踪编号、鉴权与异步任务 schema 对齐。
