from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.schemas.intent_analysis import IntentAnalysisResult
from app.services.context_provider import ContextInput
from app.services.intent_analysis_engine.registry import FunctionRegistryCatalog
from app.services.model_gateway.contract_validator import LLMResponseContractValidator


class LLMTaskEvidence(BaseModel):
    task_index: int = Field(ge=0)
    evidence_span: str = Field(min_length=1)


class LLMTaskAnalysisOutcome(BaseModel):
    result: IntentAnalysisResult | None = None
    evidence_spans: list[LLMTaskEvidence] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    contract_corrections: list[str] = Field(default_factory=list)
    contract_errors: list[str] = Field(default_factory=list)
    raw_response: str | None = None


class ImplicitTaskCandidate(BaseModel):
    normalized_text: str = Field(min_length=1)
    evidence_span: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    depends_on_previous: bool = False


class ImplicitTaskExtractionOutcome(BaseModel):
    candidates: list[ImplicitTaskCandidate] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    unsupported: bool = False
    reason: str | None = None
    raw_response: str | None = None


class LLMTaskAnalyzer:
    """Level 3 fallback for complex task-list extraction with source evidence."""

    def __init__(
        self,
        *,
        model_gateway: Any,
        registry: FunctionRegistryCatalog | None = None,
        prompt_path: Path | None = None,
        implicit_prompt_path: Path | None = None,
        confidence_threshold: float = 0.70,
        implicit_confidence_threshold: float = 0.70,
    ) -> None:
        self.model_gateway = model_gateway
        self.registry = registry or FunctionRegistryCatalog()
        self.prompt_path = prompt_path or self._default_prompt_path()
        self.implicit_prompt_path = implicit_prompt_path or self._default_implicit_prompt_path()
        self.confidence_threshold = confidence_threshold
        self.implicit_confidence_threshold = implicit_confidence_threshold
        self.contract_validator = LLMResponseContractValidator()

    def analyze(
        self,
        text: str,
        *,
        user_id: str = "unknown",
        context: ContextInput | dict[str, Any] | None = None,
    ) -> IntentAnalysisResult | None:
        return self.analyze_with_validation(text, user_id=user_id, context=context).result

    def analyze_with_validation(
        self,
        text: str,
        *,
        user_id: str = "unknown",
        context: ContextInput | dict[str, Any] | None = None,
    ) -> LLMTaskAnalysisOutcome:
        context_input = self._context_input(context)
        prompt = self._render_prompt(text=text, user_id=user_id, context=context_input)
        raw_response = self._call_model(
            [{"role": "system", "content": prompt}],
            response_schema=self._analysis_response_schema(),
        )
        return self._parse_analysis_outcome(raw_response, source_text=self._evidence_text(text, context_input))

    def extract_implicit_candidates(self, text: str) -> ImplicitTaskExtractionOutcome:
        prompt = self._render_implicit_prompt(text=text)
        try:
            raw_response = self._call_model(
                [{"role": "system", "content": prompt}],
                response_schema=None,
            )
        except Exception as error:
            return ImplicitTaskExtractionOutcome(
                rejection_reasons=[f"model_error:{type(error).__name__}"],
                reason="implicit_task_model_unavailable",
            )
        return self._parse_implicit_outcome(raw_response, source_text=text)

    def _call_model(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: dict[str, Any] | None,
    ) -> str:
        analyze = getattr(self.model_gateway, "analyze", None)
        if callable(analyze):
            response = analyze(messages=messages, response_schema=response_schema)
            return str(getattr(response, "content", response))
        chat = getattr(self.model_gateway, "chat", None)
        if callable(chat):
            return str(chat(messages))
        raise TypeError("model_gateway must provide analyze(...) or chat(...).")

    def _analysis_response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "result": IntentAnalysisResult.model_json_schema(),
                "evidence_spans": {
                    "type": "array",
                    "items": LLMTaskEvidence.model_json_schema(),
                },
            },
            "required": ["result", "evidence_spans"],
        }

    def _render_prompt(self, *, text: str, user_id: str, context: ContextInput) -> str:
        template = self.prompt_path.read_text(encoding="utf-8")
        return (
            template.replace(
                "{{INTENT_ANALYSIS_RESULT_JSON_SCHEMA}}",
                json.dumps(IntentAnalysisResult.model_json_schema(), ensure_ascii=False),
            )
            .replace("{{REGISTERED_CAPABILITIES}}", self._registered_capabilities_json())
            .replace("{{USER_TEXT}}", text)
            .replace("{{CONTEXT_JSON}}", json.dumps(context.model_dump(mode="json"), ensure_ascii=False))
            .replace("{{USER_ID}}", user_id)
        )

    def _render_implicit_prompt(self, *, text: str) -> str:
        template = self.implicit_prompt_path.read_text(encoding="utf-8")
        return (
            template.replace("{{REGISTERED_CAPABILITIES}}", self._registered_capabilities_json())
            .replace("{{USER_TEXT}}", text)
        )

    def _registered_capabilities_json(self) -> str:
        payload = [
            {
                "task_types": entry.supported_tasks,
                "description": entry.description,
                "required_inputs": entry.required_inputs,
            }
            for entry in self.registry.entries
        ]
        return json.dumps(payload, ensure_ascii=False)

    def _context_input(self, context: ContextInput | dict[str, Any] | None) -> ContextInput:
        if isinstance(context, ContextInput):
            return context
        return ContextInput.model_validate(context or {})

    def _evidence_text(self, text: str, context: ContextInput) -> str:
        if not context.has_context():
            return text
        return text + "\n" + json.dumps(context.model_dump(mode="json"), ensure_ascii=False)

    def _parse_analysis_outcome(
        self,
        raw_response: str,
        *,
        source_text: str,
    ) -> LLMTaskAnalysisOutcome:
        try:
            payload = json.loads(self._extract_json(raw_response))
            if not isinstance(payload, dict):
                raise TypeError("LLM response must be an object")
            result_payload = payload.get("result") if "result" in payload else payload
            evidence_payload = payload.get("evidence_spans")
            if result_payload is None:
                return LLMTaskAnalysisOutcome(
                    rejection_reasons=["missing_result_envelope"],
                    raw_response=raw_response,
                )
            result_payload = self._force_level3(result_payload)
            result = IntentAnalysisResult.model_validate(result_payload)
            result, general_task_corrections = self._normalize_unregistered_task_types(result)
            evidence_spans = [
                LLMTaskEvidence.model_validate(item)
                for item in (evidence_payload if isinstance(evidence_payload, list) else [])
            ]
            evidence_by_task_id = {
                result.tasks[item.task_index].task_id: item.evidence_span
                for item in evidence_spans
                if item.task_index < len(result.tasks)
            }
            contract_result = self.contract_validator.validate(result, source_text=source_text)
            result = contract_result.result
            for task_id, evidence_span in contract_result.evidence_spans_by_task_id.items():
                evidence_by_task_id.setdefault(task_id, evidence_span)
            evidence_spans = [
                LLMTaskEvidence(task_index=index, evidence_span=evidence_by_task_id[task.task_id])
                for index, task in enumerate(result.tasks)
                if task.task_id in evidence_by_task_id
            ]
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError):
            return LLMTaskAnalysisOutcome(
                rejection_reasons=["invalid_llm_evidence_envelope"],
                raw_response=raw_response,
            )

        reasons = self._validate_evidence(
            result=result,
            evidence_spans=evidence_spans,
            source_text=source_text,
        )
        reasons.extend(contract_result.errors)
        if result.tasks and result.overall_confidence < self.confidence_threshold:
            reasons.append("llm_confidence_below_threshold")
        if reasons:
            return LLMTaskAnalysisOutcome(
                result=result,
                evidence_spans=evidence_spans,
                rejection_reasons=reasons,
                contract_corrections=[
                    *general_task_corrections,
                    *contract_result.corrections,
                ],
                contract_errors=contract_result.errors,
                raw_response=raw_response,
            )

        result._llm_evidence_spans = [item.evidence_span for item in evidence_spans]
        return LLMTaskAnalysisOutcome(
            result=result,
            evidence_spans=evidence_spans,
            contract_corrections=[
                *general_task_corrections,
                *contract_result.corrections,
            ],
            contract_errors=contract_result.errors,
            raw_response=raw_response,
        )

    def _validate_evidence(
        self,
        *,
        result: IntentAnalysisResult,
        evidence_spans: list[LLMTaskEvidence],
        source_text: str,
    ) -> list[str]:
        if not result.tasks:
            return []
        reasons: list[str] = []
        if len(evidence_spans) != len(result.tasks):
            reasons.append("evidence_count_mismatch")
            return reasons
        indexes = [item.task_index for item in evidence_spans]
        if sorted(indexes) != list(range(len(result.tasks))):
            reasons.append("evidence_task_index_mismatch")
        for item in evidence_spans:
            if item.evidence_span not in source_text:
                reasons.append(f"evidence_not_in_source:{item.task_index}")
        return reasons

    def _parse_implicit_outcome(
        self,
        raw_response: str,
        *,
        source_text: str,
    ) -> ImplicitTaskExtractionOutcome:
        try:
            payload = json.loads(self._extract_json(raw_response))
            if not isinstance(payload, dict):
                raise TypeError("Implicit extraction response must be an object")
            raw_candidates = payload.get("candidates", [])
            if not isinstance(raw_candidates, list):
                raise TypeError("candidates must be a list")
            candidates = [ImplicitTaskCandidate.model_validate(item) for item in raw_candidates]
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError):
            return ImplicitTaskExtractionOutcome(
                rejection_reasons=["invalid_implicit_task_response"],
                raw_response=raw_response,
            )

        accepted: list[ImplicitTaskCandidate] = []
        reasons: list[str] = []
        for index, candidate in enumerate(candidates):
            if candidate.evidence_span not in source_text:
                reasons.append(f"implicit_evidence_not_in_source:{index}")
                continue
            if candidate.confidence < self.implicit_confidence_threshold:
                reasons.append(f"implicit_confidence_below_threshold:{index}")
                continue
            accepted.append(candidate)

        return ImplicitTaskExtractionOutcome(
            candidates=accepted,
            rejection_reasons=reasons,
            unsupported=bool(payload.get("unsupported", False)),
            reason=str(payload.get("reason")) if payload.get("reason") else None,
            raw_response=raw_response,
        )

    def _force_level3(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            payload["analysis_level"] = 3
            if not payload.get("overall_confidence"):
                tasks = payload.get("tasks")
                if isinstance(tasks, list) and tasks:
                    confidences = [
                        float(task.get("confidence", 0))
                        for task in tasks
                        if isinstance(task, dict) and task.get("confidence") is not None
                    ]
                    if confidences:
                        payload["overall_confidence"] = sum(confidences) / len(confidences)
        return payload

    def _normalize_unregistered_task_types(
        self,
        result: IntentAnalysisResult,
    ) -> tuple[IntentAnalysisResult, list[str]]:
        if not result.tasks or not self._general_task_is_registered():
            return result, []

        corrections: list[str] = []
        normalized_tasks = []
        for index, task in enumerate(result.tasks):
            task_type = task.task_type.strip()
            if not task_type:
                normalized_tasks.append(task)
                continue
            try:
                self.registry.get_by_task_type(task_type)
            except KeyError:
                normalized_tasks.append(
                    task.model_copy(
                        update={
                            "task_type": "GENERAL_TASK",
                            "missing_inputs": [],
                            "clarification_required": False,
                            "clarification_questions": [],
                            "status": "ready",
                        },
                    ),
                )
                corrections.append(f"unregistered_task_type_mapped_to_general_task:{index}:{task_type}")
                continue
            normalized_tasks.append(task)

        if not corrections:
            return result, []

        if all(task.task_type == "GENERAL_TASK" for task in normalized_tasks):
            intent_category = "通用任务型"
        else:
            intent_category = "复合任务型"
        return result.model_copy(
            update={
                "intent_category": intent_category,
                "tasks": normalized_tasks,
            },
        ), corrections

    def _general_task_is_registered(self) -> bool:
        try:
            self.registry.get_by_task_type("GENERAL_TASK")
        except KeyError:
            return False
        return True

    def _extract_json(self, raw_response: str) -> str:
        text = raw_response.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("No JSON object found.")
        return text[start : end + 1]

    def _default_prompt_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "prompts" / "intent_analysis_prompt.txt"

    def _default_implicit_prompt_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "prompts" / "implicit_task_extraction_prompt.txt"
