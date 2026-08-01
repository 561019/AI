"""Diagnostic analysis — identify major contributors and root cause hypotheses.

Two-layer logic:
1. Positioning (deterministic): rank entities by contribution magnitude, take top_n.
2. Root cause (LLM): read evidence for top entities, find common patterns.
   LLM only reads pre-computed numbers and evidence summaries — never computes,
   never fabricates evidence not present in the input.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from analysis_prediction_engine.contracts.requests import DiagnosticRequest
from analysis_prediction_engine.method_registry import DIAGNOSTIC_VERSION
from analysis_prediction_engine.services.platform_model_client import call_platform_model
from analysis_prediction_engine.traceability.provenance import build_provenance_reference

_DIAGNOSTIC_PROMPT = """你是一位经营诊断分析师。以下是一次经营诊断的输入数据，所有数值已经过确定性计算，你不需要重新计算。

诊断目标：{target_description}

主要贡献实体（按贡献度排序）：
{entities_summary}

证据记录：
{evidence_summary}

请找出主要贡献实体之间的共同问题，给出根因假设。要求：
1. 列出1-3个根因假设，按可能性排序
2. 每个假设必须引用具体的证据编号（evidence_id），不能空口无凭
3. 使用"证据显示可能是""初步判断""值得关注的是"等审慎措辞，不能写成确定事实
4. 如果证据不足以做出判断，就如实说证据不足
5. 结尾附上：「⚠️ 以上诊断假设由AI基于已有证据生成，仅供决策参考，须经真人确认后生效。」

返回JSON（仅JSON，无其他文字）：
{{"hypotheses":[{{"description":"假设描述","evidence_refs":["E001","E002"],"confidence":"plausible"}}]}}"""


def _call_llm(prompt: str, trace_id: str = "") -> dict[str, Any] | None:
    """Call platform model dispatcher for root cause hypotheses."""
    result = call_platform_model(
        trace_id=trace_id,
        task_type="analysis_prediction_diagnostic",
        system="你是一个专业的企业经营诊断助手。只基于给定的数据和证据给出分析，不编造。",
        user=prompt,
        max_tokens=800,
        temperature=0.3,
        output_kind="json",
    )
    if result["status"] != "complete":
        return None
    output = result.get("output") if isinstance(result.get("output"), dict) else {}
    return output if isinstance(output, dict) else None


def _parse_contribution(value: str | None) -> Decimal:
    """Parse contribution string to Decimal for sorting. Missing → 0."""
    if value is None:
        return Decimal("0")
    try:
        return abs(Decimal(value))
    except Exception:
        return Decimal("0")


def analyze_diagnostic(request: DiagnosticRequest) -> dict[str, object]:
    # ---- Layer 1: Positioning (deterministic) ----
    sorted_entities = sorted(
        request.entities,
        key=lambda e: _parse_contribution(e.contribution),
        reverse=True,
    )
    top_entities = sorted_entities[: request.top_n]

    major_contributors: list[dict[str, Any]] = []
    provenance: list[object] = []

    for i, entity in enumerate(top_entities):
        contributor = {
            "rank": i + 1,
            "entity_id": entity.entity_id,
            "entity_name": entity.entity_name,
            "contribution": entity.contribution,
            "metrics": dict(entity.metrics),
        }
        major_contributors.append(contributor)
        provenance.append(
            build_provenance_reference(
                output_field=f"diagnostic.major_contributors.{i}",
                source_record_id=entity.entity_id,
                source_field="contribution",
                period=request.target.metric,
                formula_version=DIAGNOSTIC_VERSION,
            )
        )

    # ---- Layer 2: Root cause (LLM reads evidence, finds patterns) ----
    entity_ids = {e.entity_id for e in top_entities}
    relevant_evidence = [e for e in request.evidence if e.entity_id in entity_ids]
    all_evidence = list(relevant_evidence) if relevant_evidence else list(request.evidence)

    entities_text = "\n".join(
        f"- {e.entity_name}({e.entity_id}): 贡献度={e.contribution}, 指标={json.dumps(dict(e.metrics), ensure_ascii=False)}"
        for e in top_entities
    )
    evidence_text = "\n".join(
        f"- 证据ID={ev.evidence_id}: 实体={ev.entity_id}, 类型={ev.evidence_type}, 摘要={ev.summary}, 日期={ev.date or '未知'}"
        for ev in all_evidence
    )

    prompt = _DIAGNOSTIC_PROMPT.format(
        target_description=f"{request.target.metric}: {request.target.description}（变化: {request.target.change}{request.target.unit}）",
        entities_summary=entities_text or "(无)",
        evidence_summary=evidence_text or "(无证据记录)",
    )

    llm_result = _call_llm(prompt, request.trace_id)

    if llm_result and llm_result.get("hypotheses"):
        hypotheses = [
            {
                "hypothesis_id": f"H{i + 1:02d}",
                "description": h.get("description", ""),
                "evidence_refs": tuple(h.get("evidence_refs", [])),
                "confidence": h.get("confidence", "plausible"),
            }
            for i, h in enumerate(llm_result["hypotheses"])
        ]
        for h in hypotheses:
            for ref in h["evidence_refs"]:
                provenance.append(
                    build_provenance_reference(
                        output_field="diagnostic.root_cause_hypotheses",
                        source_record_id=str(ref),
                        source_field="evidence",
                        period=request.target.metric,
                        formula_version=DIAGNOSTIC_VERSION,
                    )
                )
        hypothesis_status = "complete"
    elif all_evidence:
        # No LLM available, but evidence exists — list evidence without interpretation
        hypotheses = [
            {
                "hypothesis_id": "H01",
                "description": f"已收集{len(all_evidence)}条证据记录，涉及{len(entity_ids)}个实体。请人工审阅证据以确定根因。",
                "evidence_refs": tuple(ev.evidence_id for ev in all_evidence),
                "confidence": "uncertain",
            }
        ]
        hypothesis_status = "partial"
    else:
        hypotheses = [
            {
                "hypothesis_id": "H01",
                "description": "无证据记录可用，无法生成根因假设。请补充工作汇报或服务事件数据。",
                "evidence_refs": (),
                "confidence": "uncertain",
            }
        ]
        hypothesis_status = "not_computable"

    conclusions = (
        {
            "kind": "major_contributor",
            "status": "complete" if major_contributors else "not_computable",
            "details": {
                "top_n": len(major_contributors),
                "entity_ids": tuple(c["entity_id"] for c in major_contributors),
            },
        },
        {
            "kind": "root_cause_hypothesis",
            "status": hypothesis_status,
            "details": {
                "hypothesis_count": len(hypotheses),
                "evidence_count": len(all_evidence),
                "llm_used": llm_result is not None,
            },
        },
    )

    return {
        "schema_version": "v1",
        "trace_id": request.trace_id,
        "analysis_type": "diagnostic",
        "status": "complete",
        "decision_reference_only": True,
        "human_confirmation_required": True,
        "effective": False,
        "major_contributors": tuple(major_contributors),
        "root_cause_hypotheses": tuple(hypotheses),
        "conclusions": conclusions,
        "provenance": tuple(provenance),
        "calculation_metadata": (
            {"algorithm_version": DIAGNOSTIC_VERSION, "formula_version": DIAGNOSTIC_VERSION},
        ),
    }
