from dataclasses import dataclass
from typing import Any
import json
import re

from app.schemas.intent_analysis import IntentAnalysisResult
from app.schemas.semantic import SemanticResult
from app.services.context_provider import ContextInput, ContextualIntentInput
from app.services.intent_analysis_engine.conflict.detector import ConflictDetector
from app.services.intent_analysis_engine.conflict.resolver import ConflictResolver
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
from app.services.task_extraction.future_scope_filter import FutureScopeFilter


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
        self.conflict_detector = ConflictDetector()
        self.conflict_resolver = ConflictResolver()
        self.scope_filter = FutureScopeFilter()

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
            "scope_filter": None,
            "partial_coverage": None,
        }

        normalized = text.strip()
        scope_result = self.scope_filter.filter_current_scope(normalized)
        analysis_text = scope_result.filtered_text or normalized
        debug["scope_filter"] = {
            "filtered_text": scope_result.filtered_text,
            "removed_clauses": list(scope_result.removed_clauses),
            "current_scope_empty": scope_result.current_scope_empty,
            "has_explicit_exclusion": scope_result.has_explicit_exclusion,
        }
        if scope_result.current_scope_empty:
            scoped_empty_result = IntentAnalysisResult(
                original_text=normalized,
                intent_category="无当前任务",
                tasks=[],
                clarification_required=False,
                clarification_questions=[],
                analysis_level=1,
                overall_confidence=1,
            )
            self._set_final_decision(
                debug,
                selected_by="scope_filter",
                reason="Current-scope filter removed only explicitly excluded or future-scope clauses.",
            )
            return self._finalize(
                result=scoped_empty_result,
                debug=debug,
                text=normalized,
                user_id=user_id,
                conversation_id=conversation_id,
            )

        contextual_input = self._contextual_input(analysis_text, context)
        matcher_input = contextual_input.model_dump(mode="json") if contextual_input.has_context() else analysis_text
        evidence_text = self._evidence_text(contextual_input)
        debug["contextual_input"] = contextual_input.model_dump(mode="json")

        if self._is_low_information_request(analysis_text, contextual_input):
            result = IntentAnalysisResult(
                original_text=normalized,
                intent_category="待澄清",
                tasks=[],
                clarification_required=True,
                clarification_questions=["请明确需要处理的业务对象和具体动作。"],
                analysis_level=1,
                overall_confidence=0,
            )
            debug["level1_rule_result"] = {"matched": False, "rule": None}
            debug["level2_semantic_result"]["skipped_reason"] = "low_information_request"
            self._set_final_decision(
                debug,
                selected_by="clarification_gate",
                reason="Short generic input has no explicit task object and no recoverable context.",
            )
            return self._finalize(
                result=result,
                debug=debug,
                text=normalized,
                user_id=user_id,
                conversation_id=conversation_id,
            )

        fast_path_result = self.fast_path.match(analysis_text)
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

        decomposed = self.decomposer.decompose(analysis_text)
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
                analysis_text,
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
                text=analysis_text,
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
        semantic_tasklist = self._semantic_result_to_tasklist(semantic_result, analysis_text)
        if semantic_tasklist is not None:
            top_candidate = semantic_result.candidates[0] if semantic_result and semantic_result.candidates else None
            partial_result = self._try_partial_coverage(
                analysis_text,
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
                text=analysis_text,
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

        llm_outcome = self._run_llm(analysis_text, user_id=user_id, context=contextual_input.context)
        llm_result = llm_outcome.result if llm_outcome is not None else None
        llm_rejection_reasons = self._validate_llm_result(
            llm_outcome,
            source_text=evidence_text,
        )
        debug["level3_result"] = self._llm_debug(llm_outcome, llm_rejection_reasons)
        if llm_result is not None and not llm_rejection_reasons:
            if not llm_result.tasks:
                rescued = self._rescue_supported_tasklist(analysis_text)
                if rescued is not None:
                    if isinstance(debug.get("level3_result"), dict):
                        debug["level3_result"]["post_validation_recovery"] = {
                            "applied": True,
                            "reason": "LLM returned a clarification for a supported analytical operation pattern.",
                        }
                    self._set_final_decision(
                        debug,
                        selected_by="llm_guardrail_recovery",
                        reason=(
                            "Level3 was called but returned no task; a registry-bound "
                            "general recovery pattern restored a supported task list."
                        ),
                    )
                    return self._finalize(
                        result=rescued.model_copy(update={"original_text": normalized}),
                        debug=debug,
                        text=normalized,
                        user_id=user_id,
                        conversation_id=conversation_id,
                    )
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
            corrected_llm_result = self._correct_llm_business_analysis_result(llm_result, analysis_text)
            if corrected_llm_result is not llm_result:
                llm_result = corrected_llm_result
                if isinstance(debug.get("level3_result"), dict):
                    debug["level3_result"]["post_validation_recovery"] = {
                        "applied": True,
                        "reason": "Corrected a weak data-fetch task to analytical judgment based on the source text.",
                    }
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

        rejected_rescue = self._rescue_supported_tasklist(analysis_text)
        if llm_outcome is not None and rejected_rescue is not None:
            if isinstance(debug.get("level3_result"), dict):
                debug["level3_result"]["post_validation_recovery"] = {
                    "applied": True,
                    "reason": (
                        "Level3 did not return an accepted task list, but the source text "
                        "matches a registry-bound supported task pattern."
                    ),
                }
            self._set_final_decision(
                debug,
                selected_by="llm_guardrail_recovery",
                reason=(
                    "Level3 was called but did not produce an accepted result; a registry-bound "
                    "general recovery pattern restored a supported task list."
                ),
            )
            return self._finalize(
                result=rejected_rescue.model_copy(update={"original_text": normalized}),
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
            if llm_result is not None and not rejection_reasons and llm_result.tasks:
                llm_result = self._correct_llm_business_analysis_result(llm_result, segment.text)
                segment_results.append((segment.index, llm_result.model_copy(update={"original_text": segment.text})))
                continue

            rescued = self._rescue_supported_tasklist(segment.text)
            if rescued is not None:
                segment_results.append((segment.index, rescued))

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

        tasks = self._apply_partial_dependencies(tasks)

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

    def _is_low_information_request(
        self,
        text: str,
        contextual_input: ContextualIntentInput,
    ) -> bool:
        if contextual_input.has_context():
            return False

        normalized = re.sub(r"\s+", "", text.strip(" ，,。；;！？!?"))
        if not normalized:
            return False

        if re.fullmatch(r"(?:按|按照).{0,8}(?:方案|计划|规则|口径|方式)(?:来|处理|执行|做)?", normalized):
            return True
        if re.fullmatch(r"(?:处理|整理|看看|看下|看一下|检查|排查)(?:一下|下)?(?:这些|那些|这个|那个|它|这批|这份)(?:材料|文件|内容|问题|事项|东西)?", normalized):
            return True
        if re.fullmatch(r"(?:帮我|帮忙)?(?:看看|看下|看一下|确认|检查)(?:一下|下)?(?:这个|那个|它|这些|那些)?", normalized):
            return True
        if re.fullmatch(r"(?:继续|接着|再)?(?:确认|查看|看下|看一下|检查).{0,4}(?:字段|结构|列名|表头)", normalized):
            return True
        if re.fullmatch(r"(?:把)?(?:这些|那些|这个|那个|它|这块|那块).{0,4}(?:整理|处理|弄|搞)(?:一下|下|掉|好|完)?", normalized):
            return True
        if re.fullmatch(r"(?:帮忙|帮我)?(?:跟进|跟一下|跟下)(?:一下|下)?", normalized):
            return True
        if re.fullmatch(r"(?:后面|后续|下一步|接下来).{0,6}(?:怎么|如何).{0,4}(?:做|弄|处理|推进)", normalized):
            return True
        if re.fullmatch(r"(?:看看|看一下|检查|排查)?(?:有没有|是否有|有无)问题", normalized):
            return True
        return normalized == "检查分析"

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
        artifact_tasklist = self._document_artifact_phrase_to_tasklist(text, semantic_result)
        if artifact_tasklist is not None:
            return artifact_tasklist
        if self._semantic_should_defer_to_l3(top_candidate, text):
            return None
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

    def _semantic_should_defer_to_l3(self, top_candidate: Any, text: str) -> bool:
        task_type = getattr(top_candidate, "task_type", None)
        if task_type not in {"DATA_QUERY_FETCH", "EXTERNAL_DATA_FETCH"}:
            return False
        return self._looks_like_business_analysis_request(text) and not self._looks_like_fetch_request(text)

    def _correct_llm_business_analysis_result(
        self,
        result: IntentAnalysisResult,
        text: str,
    ) -> IntentAnalysisResult:
        if not result.tasks:
            return result
        if not self._looks_like_business_analysis_request(text) or self._looks_like_fetch_request(text):
            return result
        if any(task.task_type not in {"DATA_QUERY_FETCH", "EXTERNAL_DATA_FETCH"} for task in result.tasks):
            return result
        rescued = self._rescue_supported_tasklist(text, analysis_only=True)
        return rescued if rescued is not None else result

    def _rescue_supported_tasklist(
        self,
        text: str,
        *,
        analysis_only: bool = False,
    ) -> IntentAnalysisResult | None:
        normalized = text.strip()
        if not normalized:
            return None

        specs: list[tuple[int, int, str, str, list[str], float]] = []
        sequence = 0
        if not analysis_only and self._looks_like_external_fetch_request(normalized):
            specs.append(
                (
                    self._task_signal_position(normalized, ("retrieve", "fetch", "pull", "query", "export", "from")),
                    sequence,
                    "EXTERNAL_DATA_FETCH",
                    "获取外部系统数据",
                    ["operation:fetch", *self._external_system_inputs(normalized), *self._data_object_inputs(normalized)],
                    0.76,
                )
            )
            sequence += 1
        if not analysis_only and self._looks_like_sort_request(normalized):
            specs.append(
                (
                    self._task_signal_position(normalized, ("rank", "sort", "order", "排序", "排名", "排行", "倒序", "升序", "降序", "风险高低")),
                    sequence,
                    "DATA_SORT",
                    "数据排序",
                    ["operation:排序", *self._data_object_inputs(normalized)],
                    0.76,
                )
            )
            sequence += 1
        if not analysis_only and self._looks_like_aggregation_request(normalized):
            specs.append(
                (
                    self._task_signal_position(normalized, ("summarize", "summarise", "summary", "group", "aggregate", "roll", "汇总", "统计", "合计", "聚合")),
                    sequence,
                    "DATA_AGGREGATION_SUMMARY",
                    "数据统计汇总",
                    [
                        "operation:统计汇总",
                        "summary_field:count",
                        *self._classification_inputs(normalized),
                        *self._data_object_inputs(normalized),
                    ],
                    0.76,
                )
            )
            sequence += 1
        output_transformation = self._looks_like_output_transformation_request(normalized)
        if self._looks_like_business_analysis_request(normalized) and not output_transformation:
            specs.append(
                (
                    self._task_signal_position(normalized, ("analyze", "analyse", "diagnose", "assess", "evaluate", "signals", "health", "判断", "分析", "诊断", "评估", "复盘")),
                    sequence,
                    "DATA_ANALYSIS_PROBLEM",
                    "经营分析",
                    ["analysis_method:问题分析", *self._analysis_object_inputs(normalized)],
                    0.78,
                )
            )
            sequence += 1
        if not analysis_only and self._looks_like_improvement_plan_request(normalized):
            specs.append(
                (
                    self._task_signal_position(normalized, ("remediation", "improvement", "action plan", "plan", "整改", "改进", "方案", "建议", "计划")),
                    sequence,
                    "IMPROVEMENT_PLAN_GENERATE",
                    "生成方案",
                    ["topic:改进方案"],
                    0.76,
                )
            )
            sequence += 1
        if not analysis_only and self._looks_like_document_generation_request(normalized):
            specs.append(
                (
                    self._task_signal_position(normalized, ("report", "memo", "review", "document", "材料", "报告", "文档", "PPT", "周报", "月报", "季报")),
                    sequence,
                    "DOCUMENT_GENERATE",
                    "生成业务文档",
                    [f"content_type:{self._document_type_hint(normalized)}"],
                    0.76,
                )
            )

        if not specs:
            return None

        tasks = [
            self.task_factory.create_task(
                task_name=task_name,
                task_type=task_type,
                required_inputs=required_inputs,
                missing_inputs=[],
                dependencies=[],
                execution_order=index,
                confidence=confidence,
            )
            for index, (_, _, task_type, task_name, required_inputs, confidence) in enumerate(
                sorted(specs, key=lambda item: (item[0], item[1])),
                start=1,
            )
        ]
        return IntentAnalysisResult(
            original_text=normalized,
            intent_category="复合任务型" if len(tasks) > 1 else self._intent_category_for_task(tasks[0].task_type),
            tasks=tasks,
            clarification_required=False,
            clarification_questions=[],
            analysis_level=3,
            overall_confidence=min(task.confidence for task in tasks),
        )

    def _apply_partial_dependencies(self, tasks: list[Any]) -> list[Any]:
        dependent_types = {
            "DATA_AGGREGATION_SUMMARY",
            "DATA_ANALYSIS_GROUP_SUM",
            "DATA_FILTER",
            "DATA_SORT",
            "DATA_ANALYSIS_PROBLEM",
            "DATA_ANALYSIS_YOY",
            "DATA_ANALYSIS_MOM",
            "DATA_ANALYSIS_FORECAST",
            "DOCUMENT_GENERATE",
            "IMPROVEMENT_PLAN_GENERATE",
            "CONTENT_GENERATE",
        }
        updated: list[Any] = []
        previous_task_id: str | None = None
        for task in tasks:
            dependencies = list(getattr(task, "dependencies", []) or [])
            if previous_task_id and not dependencies and task.task_type in dependent_types:
                dependencies = [previous_task_id]
            current = task.model_copy(update={"dependencies": dependencies}) if dependencies != task.dependencies else task
            updated.append(current)
            if task.task_type != "QUESTION_ANSWER":
                previous_task_id = current.task_id
        return updated

    def _looks_like_sort_request(self, text: str) -> bool:
        return bool(
            re.search(r"\b(?:rank|sort|order)\b.{0,40}\b(?:risk|priority|score|amount|revenue|accounts?|customers?)\b", text, flags=re.IGNORECASE)
            or re.search(r"(?:排序|排名|排行|倒序|升序|降序|从高到低|从低到高|风险高低)", text)
        )

    def _looks_like_external_fetch_request(self, text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:retrieve|fetch|pull(?:ed)?|query|export)\b.{0,60}\b(?:CRM|ERP|OA|SAP|system|dataset|data|accounts?|customers?|records?)\b",
                text,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"\bfrom\b.{0,20}\b(?:CRM|ERP|OA|SAP|system)\b",
                text,
                flags=re.IGNORECASE,
            )
        )

    def _looks_like_aggregation_request(self, text: str) -> bool:
        return bool(
            re.search(r"\b(?:summari[sz]e(?:d)?|group(?:ed)?|aggregate(?:d)?|roll(?:ed)? up)\b.{0,40}\b(?:by|per)\b", text, flags=re.IGNORECASE)
            or re.search(r"(?:按|分).{1,24}(?:汇总|统计|合计|聚合)", text)
        )

    def _looks_like_business_analysis_request(self, text: str) -> bool:
        has_analysis_signal = bool(
            re.search(
                r"(?:分析|诊断|判断|评估|复盘|盘一下|信号|健康度|投入产出|周转|变差|下滑|下降|异常|原因|处置判断|是否值得)",
                text,
            )
            or re.search(
                r"\b(?:find signals|signals that|no longer|not producing enough|underperform|health|quality|declin|deteriorat|diagnos|assess|evaluate)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        has_business_object = bool(
            re.search(
                r"(?:客户|渠道|门店|供应链|库存|订单|回款|投诉|退款|续约|经营|销售|利润|收入|线索|风险|供应商)",
                text,
            )
            or re.search(
                r"\b(?:partner|customer|renewal|sales|revenue|channel|risk|leads?|accounts?|supply|pipeline)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        return has_analysis_signal and has_business_object

    def _looks_like_improvement_plan_request(self, text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:draft|create|write|generate|prepare|produce)\b.{0,40}\b(?:remediation|improvement|action|recovery|mitigation)\b.{0,20}\b(?:plan|proposal|recommendations?)\b",
                text,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"\b(?:remediation|improvement|action|recovery|mitigation)\s+(?:plan|proposal|recommendations?)\b",
                text,
                flags=re.IGNORECASE,
            )
            or re.search(r"(?:生成|输出|制定|起草|给出|形成).{0,20}(?:整改|改进|改善|处理|应对).{0,8}(?:方案|计划|建议|措施)", text)
        )

    def _looks_like_document_generation_request(self, text: str) -> bool:
        if re.search(
            r"\b(?:create|write|generate|prepare|produce|draft|turn)\b.{0,80}\b(?:report|memo|document|brief|review)\b",
            text,
            flags=re.IGNORECASE,
        ):
            return True
        if re.search(r"\b(?:report|memo|document|brief)\b", text, flags=re.IGNORECASE) and re.search(
            r"\b(?:manager|operating|regional|sales|renewal|business|review)\b",
            text,
            flags=re.IGNORECASE,
        ):
            return True
        return self._looks_like_document_artifact_phrase(text)

    def _looks_like_output_transformation_request(self, text: str) -> bool:
        return bool(
            re.search(
                r"\bturn\b.{0,80}\binto\b.{0,50}\b(?:report|memo|document|brief|review)\b",
                text,
                flags=re.IGNORECASE,
            )
            or re.search(r"(?:整理成|转成|做成|形成).{0,30}(?:报告|材料|文档|PPT)", text)
        )

    def _looks_like_document_artifact_phrase(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text.strip(" ，,。；;！？!?"))
        if not normalized or len(normalized) > 24:
            return False
        if re.search(r"(?:分析|诊断|原因|归因|为什么|为何|判断|预测|排序|筛选|查询|获取|计算)", normalized):
            return False
        return bool(re.search(r"(?:报告|报表|周报|日报|月报|季报|文档|材料|PPT)$", normalized, flags=re.IGNORECASE))

    def _document_artifact_phrase_to_tasklist(
        self,
        text: str,
        semantic_result: SemanticResult,
    ) -> IntentAnalysisResult | None:
        if not self._looks_like_document_artifact_phrase(text):
            return None
        top_task_type = getattr(semantic_result.candidates[0], "task_type", None) if semantic_result.candidates else None
        if top_task_type in {"DOCUMENT_GENERATE", "CONTENT_GENERATE"}:
            return None
        try:
            registry_entry = self.registry.get_by_task_type("DOCUMENT_GENERATE")
        except KeyError:
            return None
        task = self.task_factory.create_task(
            task_name="生成业务文档",
            task_type="DOCUMENT_GENERATE",
            required_inputs=[f"content_type:{self._document_type_hint(text)}"],
            missing_inputs=[],
            dependencies=[],
            execution_order=1,
            confidence=max(float(semantic_result.confidence), 0.72),
        )
        return IntentAnalysisResult(
            original_text=text,
            intent_category=registry_entry.supported_intents[0] if registry_entry.supported_intents else "文档生成型",
            tasks=[task],
            clarification_required=False,
            clarification_questions=[],
            analysis_level=2,
            overall_confidence=task.confidence,
        )

    def _document_type_hint(self, text: str) -> str:
        lowered = text.lower()
        for value in ("memo", "report", "document", "brief"):
            if value in lowered:
                return value
        for value in ("报告", "报表", "周报", "日报", "月报", "季报", "文档", "材料", "PPT"):
            if value in text:
                return value
        return "文档"

    def _task_signal_position(self, text: str, signals: tuple[str, ...]) -> int:
        lowered = text.lower()
        positions = [
            lowered.find(signal.lower())
            for signal in signals
            if lowered.find(signal.lower()) >= 0
        ]
        return min(positions) if positions else len(text)

    def _intent_category_for_task(self, task_type: str) -> str:
        try:
            entry = self.registry.get_by_task_type(task_type)
        except KeyError:
            return "复合任务型"
        return entry.supported_intents[0] if entry.supported_intents else "复合任务型"

    def _looks_like_fetch_request(self, text: str) -> bool:
        return bool(
            re.search(r"(?:查询|获取|拉取|导出|调取|调出|拿出来|取出来|明细|清单|名单|列表|台账|从.{0,12}(?:CRM|ERP|OA|SAP|系统))", text, flags=re.IGNORECASE)
            or re.search(r"\b(?:retrieve|fetch|pull(?:ed)?|query|export|from)\b.{0,30}\b(?:CRM|ERP|OA|SAP|system|dataset|data)\b", text, flags=re.IGNORECASE)
        )

    def _classification_inputs(self, text: str) -> list[str]:
        lowered = text.lower()
        if re.search(r"risk\s+tier|risk\s+level", lowered):
            return ["classification_field:risk_tier"]
        if "风险" in text:
            return ["classification_field:风险等级"]
        if "渠道" in text:
            return ["classification_field:渠道"]
        return []

    def _analysis_object_inputs(self, text: str) -> list[str]:
        for keyword in ["供应链", "回款线索", "渠道投入", "渠道", "客户", "门店", "经营", "销售", "订单", "续约", "风险"]:
            if keyword in text:
                return [f"analysis_object:{keyword}"]
        match = re.search(
            r"\b(partner enablement|qualified leads|customer renewal|renewal health|risk|channel|customer|accounts?)\b",
            text,
            flags=re.IGNORECASE,
        )
        if match is not None:
            return [f"analysis_object:{match.group(1)}"]
        return ["analysis_object:business_signal"]

    def _data_object_inputs(self, text: str) -> list[str]:
        for keyword in ["客户", "账号", "账户", "线索", "回款", "风险", "订单"]:
            if keyword in text:
                return [f"data_object:{keyword}"]
        match = re.search(r"\b(accounts?|customers?|leads?|risk|dataset)\b", text, flags=re.IGNORECASE)
        if match is not None:
            return [f"data_object:{match.group(1)}"]
        return []

    def _external_system_inputs(self, text: str) -> list[str]:
        for value in ("CRM", "ERP", "OA", "SAP"):
            if re.search(rf"\b{value}\b", text, flags=re.IGNORECASE):
                return [f"external_system:{value}"]
        match = re.search(r"\b([A-Z][A-Z0-9_-]{1,12})\s+system\b", text)
        if match is not None:
            return [f"external_system:{match.group(1)}"]
        return []

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
        result = result.model_copy(update={"original_text": text})
        conflict_resolution = None
        if result.tasks:
            context_input = self._context_from_debug(debug)
            current_input = self._current_input_from_debug(debug, fallback=text)
            conflict_detection = self.conflict_detector.detect(
                current_input=current_input,
                context=context_input,
                result=result,
            )
            resolved = self.conflict_resolver.resolve(
                result=result,
                detection=conflict_detection,
            )
            conflict_resolution = {
                "conflicts": [
                    conflict.model_dump(mode="json")
                    for conflict in conflict_detection.conflicts
                ],
                "has_blocking_conflict": conflict_detection.has_blocking_conflict,
                "conflict_count": len(conflict_detection.conflicts),
            }
            result = resolved
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
        debug["conflict_resolution"] = conflict_resolution
        debug["input_validator"] = {
            "clarification_required": validation_result.clarification_required,
            "missing_inputs": validation_result.missing_inputs,
            "required_inputs_source": validation_result.required_inputs_source,
            "input_state_details": [
                detail.model_dump(mode="json")
                for detail in validation_result.input_state_details
            ],
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

    def _context_from_debug(self, debug: dict[str, Any]) -> ContextInput:
        contextual_input = debug.get("contextual_input")
        if isinstance(contextual_input, dict):
            context_payload = contextual_input.get("context")
            if isinstance(context_payload, dict):
                return ContextInput.model_validate(context_payload)
        return ContextInput()

    def _current_input_from_debug(self, debug: dict[str, Any], *, fallback: str) -> str:
        contextual_input = debug.get("contextual_input")
        if isinstance(contextual_input, dict):
            value = contextual_input.get("user_input")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return fallback

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
