from app.schemas.intent_analysis import IntentAnalysisResult
from app.services.intent_analysis_engine import FunctionRegistryCatalog
from app.services.intent_analysis_engine.input_validator import TaskInputValidator
from app.services.intent_analysis_engine.task_factory import TaskFactory


def make_validator() -> tuple[TaskInputValidator, TaskFactory]:
    registry = FunctionRegistryCatalog()
    return TaskInputValidator(registry=registry), TaskFactory(registry)


def test_input_validator_computes_missing_inputs_from_task_type() -> None:
    validator, task_factory = make_validator()
    task = task_factory.create_task(
        task_name="计算销售提成",
        task_type="RULE_CALCULATION_COMMISSION",
        required_inputs=[],
        missing_inputs=["ignored_by_validator"],
        dependencies=[],
        execution_order=1,
        confidence=0.88,
    )

    validated = validator.validate_task(task)

    assert validated.missing_inputs == [
        "calculation_policy",
        "sales_data_source",
        "statistical_range",
    ]


def test_input_validator_uses_provided_inputs_and_aliases() -> None:
    validator, task_factory = make_validator()
    task = task_factory.create_task(
        task_name="解析文档表格",
        task_type="DOCUMENT_TABLE_PARSE",
        required_inputs=["file_type:Excel"],
        missing_inputs=[],
        dependencies=[],
        execution_order=1,
        confidence=0.94,
    )

    validation = validator.validate_tasks([validator.validate_task(task)])

    assert validation.clarification_required is False
    assert validation.missing_inputs == []
    assert validation.clarification_questions == []


def test_input_validator_builds_clarification_questions_once() -> None:
    validator, task_factory = make_validator()
    task = task_factory.create_task(
        task_name="数据统计汇总",
        task_type="DATA_AGGREGATION_SUMMARY",
        required_inputs=["summary_field:金额"],
        missing_inputs=[],
        dependencies=[],
        execution_order=1,
        confidence=0.9,
    )

    validation = validator.validate_tasks([validator.validate_task(task)])

    assert validation.clarification_required is True
    assert validation.missing_inputs == ["classification_field", "statistical_range"]
    assert validation.clarification_questions == [
        "请确认统计维度（例如区域、产品、客户）。",
        "请确认统计范围（例如时间范围、组织范围）。",
    ]
    assert [detail.input_name for detail in validation.missing_input_details] == [
        "classification_field",
        "statistical_range",
    ]
    assert validation.missing_input_details[0].validator_rule == "required_input_missing"
    assert validation.missing_input_details[0].source == "semantic_capabilities.yaml.required_inputs"
    validated = validator.validate_task(task)
    assert validated.clarification_required is True
    assert validated.status == "needs_clarification"
    assert validated.clarification_questions == validation.clarification_questions


def test_input_validator_keeps_clarification_bound_to_each_task() -> None:
    validator, task_factory = make_validator()
    data_task = task_factory.create_task(
        task_name="整理销售数据",
        task_type="DATA_QUERY_FETCH",
        required_inputs=["operation:整理归集", "data_source:销售数据"],
        missing_inputs=[],
        dependencies=[],
        execution_order=1,
        confidence=0.9,
    )
    calculation_task = task_factory.create_task(
        task_name="计算销售提成",
        task_type="RULE_CALCULATION_COMMISSION",
        required_inputs=["sales_data_source:销售数据"],
        missing_inputs=[],
        dependencies=[data_task.task_id],
        execution_order=2,
        confidence=0.88,
    )
    report_task = task_factory.create_task(
        task_name="生成经营报告",
        task_type="DOCUMENT_GENERATE",
        required_inputs=["content_type:文档", "topic:经营"],
        missing_inputs=[],
        dependencies=[calculation_task.task_id],
        execution_order=3,
        confidence=0.86,
    )

    result = IntentAnalysisResult(
        original_text="整理销售数据，计算销售提成，生成经营报告",
        intent_category="复合任务型",
        tasks=[data_task, calculation_task, report_task],
        overall_confidence=0.86,
    )

    validated, validation = validator.apply(result)
    task1, task2, task3 = validated.tasks

    assert task1.status == "ready"
    assert task1.clarification_required is False
    assert task1.clarification_questions == []

    assert task2.status == "needs_clarification"
    assert task2.clarification_required is True
    assert task2.missing_inputs == ["calculation_policy"]
    assert task2.clarification_questions == ["请提供计算规则或适用政策。"]

    assert task3.status == "waiting_dependency"
    assert task3.clarification_required is False
    assert task3.clarification_questions == []
    assert task3.blocked_reason == f"waiting_for_dependency:{task2.task_id}"

    assert validated.global_clarification_required is True
    assert validated.clarification_required is True
    assert [item.model_dump(mode="json") for item in validation.task_clarifications] == [
        {
            "task_id": task1.task_id,
            "task_type": "DATA_QUERY_FETCH",
            "missing_inputs": [],
            "clarification_required": False,
            "clarification_questions": [],
            "status": "ready",
            "blocked_reason": None,
        },
        {
            "task_id": task2.task_id,
            "task_type": "RULE_CALCULATION_COMMISSION",
            "missing_inputs": ["calculation_policy"],
            "clarification_required": True,
            "clarification_questions": ["请提供计算规则或适用政策。"],
            "status": "needs_clarification",
            "blocked_reason": None,
        },
        {
            "task_id": task3.task_id,
            "task_type": "DOCUMENT_GENERATE",
            "missing_inputs": [],
            "clarification_required": False,
            "clarification_questions": [],
            "status": "waiting_dependency",
            "blocked_reason": f"waiting_for_dependency:{task2.task_id}",
        },
    ]


def test_input_validator_distinguishes_uncertain_and_conflicting_inputs() -> None:
    validator, task_factory = make_validator()
    task = task_factory.create_task(
        task_name="计算销售提成",
        task_type="RULE_CALCULATION_COMMISSION",
        required_inputs=[
            "calculation_policy:用户已提供",
            "sales_data_source:销售数据",
            "statistical_range:去年和今年",
        ],
        missing_inputs=[],
        dependencies=[],
        execution_order=1,
        confidence=0.92,
    )
    source_text = (
        "不知道使用去年还是今年的提成政策。"
        "销售数据到底使用财务系统还是销售系统需要确认。"
        "销售提成计算对象目前没有明确，是全部销售人员还是重点区域人员。"
        "今年截至目前的数据具体截止日期需要确认。"
    )
    result = IntentAnalysisResult(
        original_text=source_text,
        intent_category="规则计算型",
        tasks=[task],
        overall_confidence=0.92,
    )

    validated, validation = validator.apply(result)
    states = {detail.input_name: detail.state for detail in validation.input_state_details}

    assert states == {
        "calculation_policy": "uncertain",
        "sales_data_source": "conflict",
        "calculation_object": "uncertain",
        "statistical_range": "uncertain",
    }
    assert validation.missing_inputs == []
    assert validation.uncertain_inputs == [
        "calculation_policy",
        "calculation_object",
        "statistical_range",
    ]
    assert validation.conflict_inputs == ["sales_data_source"]
    assert validated.tasks[0].missing_inputs == [
        "calculation_policy",
        "sales_data_source",
        "calculation_object",
        "statistical_range",
    ]
    assert validated.clarification_questions == [
        "请确认销售提成适用的政策版本（去年版或今年调整版）。",
        "请确认销售数据来源（财务系统或销售系统，以哪个为准）。",
        "请确认销售提成的计算对象（全部销售人员或指定区域人员）。",
        "请确认今年截至目前数据的最终截止日期。",
    ]
