from dataclasses import dataclass
from typing import Any
import json

from app.schemas.intent_analysis import IntentAnalysisResult
from app.schemas.semantic import SemanticResult
from app.services.context_provider import ContextInput, ContextualIntentInput
from app.services.intent_analysis_engine.decomposer import TaskDecomposer
from app.services.intent_analysis_engine.fast_path import QuestionFastPath
from app.services.intent_analysis_engine.input_validator import InputValidationResult, TaskInputValidator
from app.services.intent_analysis_engine.llm import LLMTaskAnalysisOutcome, LLMTaskAnalyzer
from app.services.intent_analysis_engine.operation_rules import OperationRuleMatcher
from app.services.intent_analysis_engine.partial_coverage_detector import (
    CoverageSegment,
    MatchedTaskBinding,
    PartialCoverageDetector,
    PartialCoverageResult,
)
from app.services.intent_analysis_engine.registry import FunctionRegistryCatalog
from app.services.intent_analysis_engine.task_factory import TaskFactory
from app.services.model_gateway import ModelComplexity, ModelRouter


@dataclass(frozen=True)
class IntentAnalysisWithDebug:
    result: IntentAnalysisResult
    debug: dict[str, Any]


class StandardIntentAnalyzer:
    """Natural language understanding to standard task list, without business execution."""

    def __init__(
        self,
        *,
        registry: FunctionRegistryCatalog | None = None,
        semantic_matcher: Any | None = None,
        llm_analyzer: LLMTaskAnalyzer | None = None,
        intent_record_service: Any | None = None,
        semantic_threshold: float = 0.50,
        llm_confidence_threshold: float = 0.70,
        model_router: ModelRouter | None = None,
    ) -> None:
        self.registry = registry or FunctionRegistryCatalog()
        self.semantic_matcher = semantic_matcher
        self.llm_analyzer = llm_analyzer
        self.intent_record_service = intent_record_service
        self.semantic_threshold = semantic_threshold
        self.llm_confidence_threshold = llm_confidence_threshold
        self.model_router = model_router or ModelRouter()

        task_factory = TaskFactory(self.registry)
        self.fast_path = QuestionFastPath(task_factory)
        self.operation_rules = OperationRuleMatcher(task_factory)
        self.decomposer = TaskDecomposer(task_factory)
        self.input_validator = TaskInputValidator(registry=self.registry)
        self.task_factory = task_factory
        self.partial_coverage_detector = PartialCoverageDetector()

    def analyze(
        self,
        *,
        text: str,
        user_id: str,
        conversation_id: str,
        context: Any | None = None,
    ) -> IntentAnalysisResult:
        return self.analyze_with_debug(
            text=text,
            user_id=user_id,
            conversation_id=conversation_id,
            context=context,
        ).result

    def analyze_with_debug(
        self,
        *,
        text: str,
        user_id: str,
        conversation_id: str,
        context: Any | None = None,
    ) -> IntentAnalysisWithDebug:
        debug: dict[str, Any] = {
            "fast_path": None,
            "level1_result": None,
            "level2_result": None,
            "level3_result": None,
            "level1_rule_result": {"matched": False, "rule": None},
            "level2_semantic_result": {
                "matched": False,
                "top_candidates": [],
                "threshold": self.semantic_threshold,
            },
            "final_decision": None,
            "input_validator": None,
            "input_validation_result": None,
            "final_tasklist": None,
            "contextual_input": None,
            "partial_coverage": None,
        }

        normalized = text.strip()
        contextual_input = self._contextual_input(normalized, context)
        matcher_input = contextual_input.model_dump(mode="json") if contextual_input.has_context() else normalized
        evidence_text = self._evidence_text(contextual_input)
        debug["contextual_input"] = contextual_input.model_dump(mode="json")

        fast_path_result = self.fast_path.match(normalized)
        if fast_path_result is not None:
            debug["fast_path"] = {"matched": True, "type": "question_fast_path"}
            debug["level1_rule_result"] = {"matched": True, "rule": "question_fast_path"}
            debug["level2_semantic_result"]["skipped_reason"] = "level1_rule_matched"
            self._set_final_decision(
                debug,
                selected_by="rule",
                reason="QuestionFastPath matched a simple knowledge question before semantic or LLM fallback.",
            )
            return self._finalize(
                result=fast_path_result,
                debug=debug,
                text=normalized,
                user_id=user_id,
                conversation_id=conversation_id,
            )

        decomposed = self.decomposer.decompose(normalized)
        if decomposed is not None:
            debug["level1_rule_result"] = {"matched": True, "rule": "task_decomposer"}
            debug["level2_semantic_result"]["skipped_reason"] = "level1_rule_matched"
            debug["level3_result"] = {
                "matched": True,
                "source": "TaskDecomposer",
                "result": decomposed.model_dump(mode="json"),
            }
            self._set_final_decision(
                debug,
                selected_by="rule",
                reason="TaskDecomposer matched a deterministic multi-task pattern.",
            )
            return self._finalize(
                result=decomposed,
                debug=debug,
                text=normalized,
                user_id=user_id,
                conversation_id=conversation_id,
            )

        operation_match = self.operation_rules.match(matcher_input)
        if operation_match is not None:
            debug["level1_rule_result"] = {
                "matched": True,
                "rule": operation_match.rule_name,
                "rule_priority": operation_match.rule_priority,
            }
            debug["level2_semantic_result"]["skipped_reason"] = "level1_rule_matched"
            debug["level1_result"] = {
                "matched": True,
                "source": "OperationRuleMatcher",
                "rule_name": operation_match.rule_name,
                "rule_priority": operation_match.rule_priority,
                "result": operation_match.result.model_dump(mode="json"),
            }
            partial_result = self._try_partial_coverage(
                normalized,
                matched_result=operation_match.result,
                matched_source="rule",
                user_id=user_id,
                context=contextual_input.context,
                debug=debug,
            )
            if partial_result is not None:
                return self._finalize(
                    result=partial_result,
                    debug=debug,
                    text=normalized,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
            self._record_complete_partial_debug(
                text=normalized,
                matched_result=operation_match.result,
                matched_source="rule",
                debug=debug,
            )
            self._set_final_decision(
                debug,
                selected_by="rule",
                reason=f"Level1 rule '{operation_match.rule_name}' matched the user text.",
            )
            return self._finalize(
                result=operation_match.result,
                debug=debug,
                text=normalized,
                user_id=user_id,
                conversation_id=conversation_id,
            )

        semantic_result = self._run_semantic(contextual_input)
        debug["level2_result"] = self._dump_model(semantic_result) if semantic_result is not None else None
        debug["level2_semantic_result"] = self._semantic_debug(semantic_result)
        semantic_tasklist = self._semantic_result_to_tasklist(semantic_result, normalized)
        if semantic_tasklist is not None:
            top_candidate = semantic_result.candidates[0] if semantic_result and semantic_result.candidates else None
            partial_result = self._try_partial_coverage(
                normalized,
                matched_result=semantic_tasklist,
                matched_source="semantic",
                user_id=user_id,
                context=contextual_input.context,
                debug=debug,
            )
            if partial_result is not None:
                return self._finalize(
                    result=partial_result,
                    debug=debug,
                    text=normalized,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
            self._record_complete_partial_debug(
                text=normalized,
                matched_result=semantic_tasklist,
                matched_source="semantic",
                debug=debug,
            )
            self._set_final_decision(
                debug,
                selected_by="semantic",
                reason=(
                    "Level2 semantic matcher selected the top task_type "
                    f"{getattr(top_candidate, 'task_type', None)} with confidence "
                    f"{semantic_result.confidence:.4f}."
                ),
            )
            return self._finalize(
                result=semantic_tasklist,
                debug=debug,
                text=normalized,
                user_id=user_id,
                conversation_id=conversation_id,
            )

        llm_outcome = self._run_llm(normalized, user_id=user_id, context=contextual_input.context)
        llm_result = llm_outcome.result if llm_outcome is not None else None
        llm_rejection_reasons = self._validate_llm_result(
            llm_outcome,
            source_text=evidence_text,
        )
        debug["level3_result"] = self._llm_debug(llm_outcome, llm_rejection_reasons)
        if llm_result is not None and not llm_rejection_reasons:
            if not llm_result.tasks:
                self._set_final_decision(
                    debug,
                    selected_by="llm_safe_rejection",
                    reason="Level3 found no supported task and returned a clarification response.",
                )
                return self._finalize(
                    result=llm_result.model_copy(update={"original_text": normalized}),
                    debug=debug,
                    text=normalized,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
            self._set_final_decision(
                debug,
                selected_by="llm",
                reason=(
                    "Level1 and Level2 did not produce a final task list; Level3 returned "
                    "a registry-bound structured task list with source evidence."
                ),
            )
            return self._finalize(
                result=llm_result.model_copy(update={"original_text": normalized}),
                debug=debug,
                text=normalized,
                user_id=user_id,
                conversation_id=conversation_id,
            )

        fallback = IntentAnalysisResult(
            original_text=normalized,
            intent_category="智能问答型",
            tasks=[],
            clarification_required=True,
            clarification_questions=["请补充要处理的具体目标、数据来源或输出形式。"],
            analysis_level=3,
            overall_confidence=0,
        )
        self._set_final_decision(
            debug,
            selected_by="fallback",
            reason=(
                "No matcher produced a validated task; returning clarification fallback."
                + (
                    f" Level3 rejection reasons: {', '.join(llm_rejection_reasons)}."
                    if llm_rejection_reasons
                    else ""
                )
            ),
        )
        return self._finalize(
            result=fallback,
            debug=debug,
            text=normalized,
            user_id=user_id,
            conversation_id=conversation_id,
        )

    def _try_partial_coverage(
        self,
        text: str,
        *,
        matched_result: IntentAnalysisResult,
        matched_source: str,
        user_id: str,
        context: ContextInput,
        debug: dict[str, Any],
    ) -> IntentAnalysisResult | None:
        segments = self.partial_coverage_detector.segment(text)
        if len(segments) <= 1 or not matched_result.tasks:
            return None

        bindings = self._bind_tasks_to_segments(
            matched_result=matched_result,
            matched_source=matched_source,
            segments=segments,
            context=context,
        )
        coverage = self.partial_coverage_detector.detect(
            original_text=text,
            segments=segments,
            matched_tasks=bindings,
        )
        l1_tasks = self._bound_task_debug(bindings, source="rule")
        l2_tasks = self._bound_task_debug(bindings, source="semantic")

        if not coverage.need_llm:
            debug["partial_coverage"] = self.partial_coverage_detector.debug_payload(
                result=coverage,
                l1_tasks=l1_tasks,
                l2_tasks=l2_tasks,
                llm_called=False,
                l3_compensation_success=False,
            )
            return None

        if self.llm_analyzer is None:
            debug["partial_coverage"] = self.partial_coverage_detector.debug_payload(
                result=coverage,
                l1_tasks=l1_tasks,
                l2_tasks=l2_tasks,
                llm_called=False,
                l3_compensation_success=False,
            )
            return None

        segment_results: list[tuple[int, IntentAnalysisResult]] = []
        bound_segment_indexes = {binding.segment_index for binding in bindings}
        for segment in segments:
            if segment.index in bound_segment_indexes:
                segment_results.append((segment.index, matched_result))
                continue

            llm_outcome = self._run_llm(segment.text, user_id=user_id, context=context)
            llm_result = llm_outcome.result if llm_outcome is not None else None
            rejection_reasons = self._validate_llm_result(
                llm_outcome,
                source_text=self._evidence_text(ContextualIntentInput(user_input=segment.text, context=context)),
            )
            if debug.get("level3_result") is None:
                debug["level3_result"] = []
            if isinstance(debug["level3_result"], list):
                debug["level3_result"].append(
                    {
                        "segment": segment.model_dump(mode="json"),
                        "result": self._llm_debug(llm_outcome, rejection_reasons),
                    }
                )
            if llm_result is not None and not rejection_reasons:
                segment_results.append((segment.index, llm_result.model_copy(update={"original_text": segment.text})))

        merged = self._merge_partial_results(
            original_text=text,
            matched_result=matched_result,
            coverage=coverage,
            segment_results=segment_results,
        )
        uncovered_indexes = {segment.index for segment in coverage.uncovered_segments}
        compensated_indexes = {
            index
            for index, result in segment_results
            if index in uncovered_indexes and result.tasks
        }
        l3_compensation_success = bool(uncovered_indexes) and uncovered_indexes <= compensated_indexes
        debug["partial_coverage"] = self.partial_coverage_detector.debug_payload(
            result=coverage,
            l1_tasks=l1_tasks,
            l2_tasks=l2_tasks,
            llm_called=True,
            l3_compensation_success=l3_compensation_success,
        )
        self._set_final_decision(
            debug,
            selected_by="partial_coverage_l3",
            reason=(
                "Level1/Level2 covered only part of the segmented request; "
                "Level3 was called only for uncovered segments."
            ),
        )
        return merged

    def _record_complete_partial_debug(
        self,
        *,
        text: str,
        matched_result: IntentAnalysisResult,
        matched_source: str,
        debug: dict[str, Any],
    ) -> None:
        if debug.get("partial_coverage") is not None or not matched_result.tasks:
            return
        segments = self.partial_coverage_detector.segment(text)
        if len(segments) != 1:
            return
        segment = segments[0]
        bindings = [
            MatchedTaskBinding(
                task_id=task.task_id,
                task_type=task.task_type,
                task_description=task.task_description,
                segment_index=segment.index,
                segment_text=segment.text,
                source=matched_source,
            )
            for task in matched_result.tasks
        ]
        coverage = self.partial_coverage_detector.detect(
            original_text=text,
            segments=segments,
            matched_tasks=bindings,
        )
        debug["partial_coverage"] = self.partial_coverage_detector.debug_payload(
            result=coverage,
            l1_tasks=self._bound_task_debug(bindings, source="rule"),
            l2_tasks=self._bound_task_debug(bindings, source="semantic"),
            llm_called=False,
            l3_compensation_success=False,
        )

    def _bind_tasks_to_segments(
        self,
        *,
        matched_result: IntentAnalysisResult,
        matched_source: str,
        segments: list[CoverageSegment],
        context: ContextInput,
    ) -> list[MatchedTaskBinding]:
        bindings: list[MatchedTaskBinding] = []
        used_segments: set[int] = set()
        for task in matched_result.tasks:
            segment = self._find_task_segment(
                task_type=task.task_type,
                matched_source=matched_source,
                segments=segments,
                context=context,
                used_segments=used_segments,
            )
            if segment is None:
                continue
            used_segments.add(segment.index)
            bindings.append(
                MatchedTaskBinding(
                    task_id=task.task_id,
                    task_type=task.task_type,
                    task_description=task.task_description,
                    segment_index=segment.index,
                    segment_text=segment.text,
                    source=matched_source,
                )
            )
        return bindings

    def _find_task_segment(
        self,
        *,
        task_type: str,
        matched_source: str,
        segments: list[CoverageSegment],
        context: ContextInput,
        used_segments: set[int],
    ) -> CoverageSegment | None:
        for segment in segments:
            if segment.index in used_segments:
                continue
            if matched_source == "rule":
                match = self.operation_rules.match(self._segment_matcher_input(segment.text, context))
                if match is not None and any(task.task_type == task_type for task in match.result.tasks):
                    return segment
            elif matched_source == "semantic":
                semantic = self._run_semantic(ContextualIntentInput(user_input=segment.text, context=context))
                tasklist = self._semantic_result_to_tasklist(semantic, segment.text)
                if tasklist is not None and any(task.task_type == task_type for task in tasklist.tasks):
                    return segment
        return None

    def _segment_matcher_input(self, text: str, context: ContextInput) -> str | dict[str, Any]:
        contextual_input = ContextualIntentInput(user_input=text, context=context)
        return contextual_input.model_dump(mode="json") if contextual_input.has_context() else text

    def _bound_task_debug(
        self,
        bindings: list[MatchedTaskBinding],
        *,
        source: str,
    ) -> list[dict[str, Any]]:
        return [
            binding.model_dump(mode="json")
            for binding in bindings
            if binding.source == source
        ]

    def _merge_partial_results(
        self,
        *,
        original_text: str,
        matched_result: IntentAnalysisResult,
        coverage: PartialCoverageResult,
        segment_results: list[tuple[int, IntentAnalysisResult]],
    ) -> IntentAnalysisResult:
        if not segment_results:
            return matched_result.model_copy(update={"original_text": original_text})

        seen_task_ids: set[str] = set()
        tasks = []
        questions: list[str] = []
        categories: list[str] = []
        analysis_level = matched_result.analysis_level
        for _, result in sorted(segment_results, key=lambda item: item[0]):
            if result.intent_category and result.intent_category not in categories:
                categories.append(result.intent_category)
            analysis_level = max(analysis_level, result.analysis_level)
            for task in result.tasks:
                if task.task_id in seen_task_ids:
                    continue
                seen_task_ids.add(task.task_id)
                tasks.append(task)
            for question in result.clarification_questions:
                if question not in questions:
                    questions.append(question)

        segments_with_tasks = {
            index
            for index, result in segment_results
            if result.tasks
        }
        uncovered_with_no_task = any(
            segment.index not in segments_with_tasks
            for segment in coverage.uncovered_segments
        )
        return IntentAnalysisResult(
            original_text=original_text,
            intent_category=categories[0] if len(categories) == 1 else "复合任务型",
            tasks=tasks,
            clarification_required=bool(questions) or uncovered_with_no_task,
            clarification_questions=questions,
            analysis_level=analysis_level,
            overall_confidence=min((task.confidence for task in tasks), default=0),
        )

    def _run_semantic(self, contextual_input: ContextualIntentInput) -> SemanticResult | None:
        if self.semantic_matcher is None:
            return None

        try:
            if contextual_input.has_context():
                return self.semantic_matcher.analyze(contextual_input.model_dump(mode="json"))
            return self.semantic_matcher.analyze(contextual_input.user_input)
        except Exception as error:
            return SemanticResult.unmatched(candidates=[])

    def _semantic_result_to_tasklist(
        self,
        semantic_result: SemanticResult | None,
        text: str,
    ) -> IntentAnalysisResult | None:
        if (
            semantic_result is None
            or not semantic_result.matched
            or not semantic_result.candidates
            or semantic_result.confidence < self.semantic_threshold
        ):
            return None

        top_candidate = semantic_result.candidates[0]
        capability_tasklist = self._capability_candidate_to_tasklist(top_candidate, semantic_result, text)
        if capability_tasklist is not None:
            return capability_tasklist

        task_type, task_name, intent_category = self._task_for_legacy_function(top_candidate.function_code)
        if task_type is None:
            return None

        task = self.task_factory.create_task(
            task_name=task_name,
            task_type=task_type,
            required_inputs=[f"source_text:{text}"],
            missing_inputs=[],
            dependencies=[],
            execution_order=1,
            confidence=semantic_result.confidence,
        )
        return IntentAnalysisResult(
            original_text=text,
            intent_category=intent_category,
            tasks=[task],
            clarification_required=False,
            clarification_questions=[],
            analysis_level=2,
            overall_confidence=semantic_result.confidence,
        )

    def _capability_candidate_to_tasklist(
        self,
        top_candidate: Any,
        semantic_result: SemanticResult,
        text: str,
    ) -> IntentAnalysisResult | None:
        task_type = getattr(top_candidate, "task_type", None)
        if not task_type:
            return None

        try:
            registry_entry = self.registry.get_by_task_type(task_type)
        except KeyError:
            return None

        task = self.task_factory.create_task(
            task_name=getattr(top_candidate, "task_name", None) or task_type,
            task_type=task_type,
            required_inputs=[],
            missing_inputs=[],
            dependencies=[],
            execution_order=1,
            confidence=semantic_result.confidence,
        )
        return IntentAnalysisResult(
            original_text=text,
            intent_category=getattr(top_candidate, "intent_category", None)
            or (registry_entry.supported_intents[0] if registry_entry.supported_intents else "智能问答型"),
            tasks=[task],
            clarification_required=False,
            clarification_questions=[],
            analysis_level=2,
            overall_confidence=semantic_result.confidence,
        )

    def _task_for_legacy_function(self, function_code: str) -> tuple[str | None, str, str]:
        mapping = {
            "FUNC_REPORT_GENERATION": ("DOCUMENT_GENERATE", "生成业务文档", "文档生成型"),
            "FUNC_INTELLIGENT_QA": ("QUESTION_ANSWER", "智能问答", "智能问答型"),
            "FUNC_DATA_PROCESSING": ("DATA_AGGREGATION_SUMMARY", "数据处理汇总", "数据分析型"),
            "FUNC_CONTENT_CREATION": ("CONTENT_GENERATE", "内容生成", "内容生成型"),
        }
        return mapping.get(function_code, (None, "", ""))

    def _run_llm(
        self,
        text: str,
        *,
        user_id: str,
        context: ContextInput,
    ) -> LLMTaskAnalysisOutcome | None:
        if self.llm_analyzer is None:
            return None
        route_decision = self.model_router.route(complexity=ModelComplexity.HIGH)
        if not route_decision.use_llm:
            return LLMTaskAnalysisOutcome(
                rejection_reasons=[f"llm_skipped_by_model_router:{route_decision.reason}"],
            )

        try:
            if isinstance(self.llm_analyzer, LLMTaskAnalyzer):
                return self.llm_analyzer.analyze_with_validation(text, user_id=user_id, context=context)
            result = self.llm_analyzer.analyze(text, user_id=user_id)
            return LLMTaskAnalysisOutcome(result=result)
        except Exception as error:
            return LLMTaskAnalysisOutcome(
                rejection_reasons=[f"model_error:{type(error).__name__}"],
            )

    def _validate_llm_result(
        self,
        outcome: LLMTaskAnalysisOutcome | None,
        *,
        source_text: str,
    ) -> list[str]:
        if outcome is None:
            return []
        reasons = list(outcome.rejection_reasons)
        result = outcome.result
        if result is None:
            if not reasons:
                reasons.append("llm_result_missing")
            return reasons
        if not result.tasks:
            if not result.clarification_required:
                reasons.append("empty_llm_result_without_clarification")
            return reasons
        if result.overall_confidence < self.llm_confidence_threshold:
            reasons.append("llm_confidence_below_threshold")

        evidence_by_index = {item.task_index: item.evidence_span for item in outcome.evidence_spans}
        if len(evidence_by_index) != len(result.tasks):
            reasons.append("llm_evidence_incomplete")

        task_ids = {task.task_id for task in result.tasks}
        for index, task in enumerate(result.tasks):
            evidence_span = evidence_by_index.get(index)
            if not evidence_span or evidence_span not in source_text:
                reasons.append(f"llm_evidence_invalid:{index}")
            try:
                self.registry.get_by_task_type(task.task_type)
            except KeyError:
                reasons.append(f"unregistered_task_type:{task.task_type}")
                continue
            if any(dependency not in task_ids for dependency in task.dependencies):
                reasons.append(f"unknown_dependency:{index}")
            if task.task_id in task.dependencies:
                reasons.append(f"self_dependency:{index}")
        return list(dict.fromkeys(reasons))

    def _llm_debug(
        self,
        outcome: LLMTaskAnalysisOutcome | None,
        rejection_reasons: list[str],
    ) -> dict[str, Any] | None:
        if outcome is None:
            return None
        return {
            "result": self._dump_model(outcome.result) if outcome.result is not None else None,
            "evidence_spans": [item.model_dump(mode="json") for item in outcome.evidence_spans],
            "validation": {
                "accepted": outcome.result is not None and not rejection_reasons,
                "rejection_reasons": rejection_reasons,
                "contract_corrections": outcome.contract_corrections,
                "contract_errors": outcome.contract_errors,
                "registry_checked": bool(outcome.result and outcome.result.tasks),
                "evidence_checked": bool(outcome.result and outcome.result.tasks),
            },
        }

    def _finalize(
        self,
        *,
        result: IntentAnalysisResult,
        debug: dict[str, Any],
        text: str,
        user_id: str,
        conversation_id: str,
    ) -> IntentAnalysisWithDebug:
        if result.tasks:
            checked, validation_result = self.input_validator.apply(result)
        else:
            checked = result
            validation_result = InputValidationResult(
                clarification_required=result.clarification_required,
                missing_inputs=[],
                clarification_questions=result.clarification_questions,
            )
        recorded = self._record_result(
            result=checked,
            text=text,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        debug["input_validation_result"] = validation_result.model_dump(mode="json")
        debug["input_validator"] = {
            "clarification_required": validation_result.clarification_required,
            "missing_inputs": validation_result.missing_inputs,
            "task_clarifications": [
                item.model_dump(mode="json")
                for item in validation_result.task_clarifications
            ],
            "rules": [
                detail.model_dump(mode="json")
                for detail in validation_result.missing_input_details
            ],
        }
        debug["final_tasklist"] = recorded.model_dump(mode="json")
        self._complete_final_decision(debug, recorded)
        return IntentAnalysisWithDebug(result=recorded, debug=debug)

    def _record_result(
        self,
        *,
        result: IntentAnalysisResult,
        text: str,
        user_id: str,
        conversation_id: str,
    ) -> IntentAnalysisResult:
        if self.intent_record_service is None:
            return result

        first_task = result.tasks[0] if result.tasks else None
        try:
            record = self.intent_record_service.record_intent_result(
                request_text=text,
                user_id=user_id,
                conversation_id=conversation_id,
                analysis_level=result.analysis_level,
                matched_function=first_task.task_type if first_task else None,
                confidence=result.overall_confidence,
                result="clarification_required" if result.clarification_required else "success",
            )
        except Exception:
            return result

        return result.model_copy(update={"request_id": record.id})

    def _dump_model(self, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value

    def _contextual_input(self, text: str, context: Any | None) -> ContextualIntentInput:
        if isinstance(context, ContextInput):
            context_input = context
        else:
            context_input = ContextInput.model_validate(context or {})
        return ContextualIntentInput(user_input=text, context=context_input)

    def _evidence_text(self, contextual_input: ContextualIntentInput) -> str:
        if not contextual_input.has_context():
            return contextual_input.user_input
        return (
            contextual_input.user_input
            + "\n"
            + json.dumps(contextual_input.context.model_dump(mode="json"), ensure_ascii=False)
        )

    def _semantic_debug(self, semantic_result: SemanticResult | None) -> dict[str, Any]:
        if semantic_result is None:
            return {
                "matched": False,
                "top_candidates": [],
                "threshold": self.semantic_threshold,
                "skipped_reason": "semantic_matcher_not_configured",
            }

        return {
            "matched": semantic_result.matched,
            "confidence": semantic_result.confidence,
            "similarity_score": semantic_result.similarity_score,
            "threshold": self.semantic_threshold,
            "top_candidates": [
                {
                    "task_type": candidate.task_type,
                    "confidence": candidate.confidence,
                    "similarity_score": candidate.similarity_score,
                }
                for candidate in semantic_result.candidates[:5]
            ],
        }

    def _set_final_decision(self, debug: dict[str, Any], *, selected_by: str, reason: str) -> None:
        debug["final_decision"] = {
            "selected_by": selected_by,
            "reason": reason,
            "selected_tasks": [],
        }

    def _complete_final_decision(self, debug: dict[str, Any], result: IntentAnalysisResult) -> None:
        decision = debug.get("final_decision") or {
            "selected_by": "unknown",
            "reason": "No explicit decision reason was recorded.",
        }
        decision["selected_tasks"] = [
            {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "action": task.action,
                "object": task.object,
                "confidence": task.confidence,
            }
            for task in result.tasks
        ]
        debug["final_decision"] = decision
