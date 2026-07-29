from app.schemas.intent_analysis import TaskItem
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer
from app.services.intent_analysis_engine.input_validator import TaskInputValidator
from app.services.intent_analysis_engine.task_factory import TaskFactory
from app.services.intent_analysis_engine.task_schema import TaskTypeSchemaCatalog


def make_validator() -> tuple[TaskInputValidator, TaskFactory]:
    registry = FunctionRegistryCatalog()
    return TaskInputValidator(registry=registry), TaskFactory(registry)


def make_analyzer() -> StandardIntentAnalyzer:
    return StandardIntentAnalyzer(
        registry=FunctionRegistryCatalog(),
        semantic_matcher=None,
        llm_analyzer=None,
        intent_record_service=None,
    )


def test_schema_catalog_defines_required_inputs_for_high_frequency_tasks() -> None:
    catalog = TaskTypeSchemaCatalog()

    assert catalog.required_inputs_for("RULE_CALCULATION_COMMISSION") == ["calculation_policy"]
    assert catalog.required_inputs_for("DATA_QUERY_FETCH") == ["data_source"]
    assert catalog.required_inputs_for("DATA_AGGREGATION_SUMMARY") == [
        "statistical_range",
        "summary_field",
    ]
    assert catalog.required_inputs_for("DATA_ANALYSIS_GROUP_SUM") == ["statistical_range"]
    assert catalog.required_inputs_for("DATA_ANALYSIS_PROBLEM") == ["analysis_object"]
    assert catalog.required_inputs_for("DOCUMENT_GENERATE") == ["document_type"]
    assert catalog.required_inputs_for("PROCESS_HANDLE") == ["process_name"]
    assert catalog.required_inputs_for("WORKFLOW_START") == ["process_name"]
    assert catalog.required_inputs_for("EXTERNAL_SYSTEM_SUBMIT") == ["external_system"]


def test_rule_calculation_uses_policy_as_the_only_required_input() -> None:
    validator, task_factory = make_validator()
    task = task_factory.create_task(
        task_name="计算销售提成",
        task_type="RULE_CALCULATION_COMMISSION",
        required_inputs=["calculation_policy:2026规则"],
        missing_inputs=["calculation_basis"],
        dependencies=[],
        execution_order=1,
        confidence=0.9,
    )

    validated = validator.validate_task(task, source_text="使用2026规则计算销售提成")

    assert validated.missing_inputs == []
    assert validated.clarification_required is False
    assert "calculation_basis" not in validated.missing_inputs


def test_rule_calculation_without_policy_requires_clarification() -> None:
    validator, task_factory = make_validator()
    task = task_factory.create_task(
        task_name="计算销售提成",
        task_type="RULE_CALCULATION_COMMISSION",
        required_inputs=[],
        missing_inputs=[],
        dependencies=[],
        execution_order=1,
        confidence=0.9,
    )

    validated = validator.validate_task(task, source_text="计算销售提成")

    assert validated.missing_inputs == ["calculation_policy"]
    assert validated.clarification_required is True


def test_bare_schema_field_names_do_not_count_as_provided_values() -> None:
    validator, task_factory = make_validator()
    task = task_factory.create_task(
        task_name="Analyze business operation problem",
        task_type="DATA_ANALYSIS_PROBLEM",
        required_inputs=["analysis_object", "analysis_method"],
        missing_inputs=[],
        dependencies=[],
        execution_order=1,
        confidence=0.7,
    )

    validated = validator.validate_task(
        task,
        source_text="business operation problem analysis",
    )

    assert validated.missing_inputs == ["analysis_object"]
    assert validated.clarification_required is True
    assert validated.status == "needs_clarification"


def test_document_generation_does_not_require_user_or_project_metadata() -> None:
    analyzer = make_analyzer()

    result = analyzer.analyze(
        text="生成销售报表",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks[0].task_type == "DOCUMENT_GENERATE"
    assert result.tasks[0].missing_inputs == []
    assert result.clarification_required is False
    assert not {
        "user_name",
        "department",
        "project_name",
    }.intersection(result.tasks[0].missing_inputs)


def test_unknown_task_type_has_no_dynamic_required_inputs() -> None:
    validator = TaskInputValidator(registry=FunctionRegistryCatalog())
    task = TaskItem(
        task_type="UNKNOWN_TASK_TYPE",
        task_description="未知任务",
        required_inputs=["free_form_field:任意值"],
        missing_inputs=["free_form_field"],
        confidence=0.5,
    )

    validated = validator.validate_task(task)
    validation = validator.validate_tasks([validated])

    assert validated.missing_inputs == []
    assert validated.clarification_required is False
    assert validation.required_inputs_source == "task_type_schema"
    assert validation.input_state_details == []


def test_debug_marks_schema_and_value_sources() -> None:
    analyzer = make_analyzer()

    analysis = analyzer.analyze_with_debug(
        text="计算销售提成",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert analysis.debug["input_validator"]["required_inputs_source"] == "task_type_schema"
    assert analysis.debug["input_validator"]["rules"][0]["required_inputs_source"] == "task_type_schema"


def test_data_object_does_not_satisfy_data_source_requirement() -> None:
    analyzer = make_analyzer()

    result = analyzer.analyze(
        text="客户资料取出来",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks[0].task_type == "DATA_QUERY_FETCH"
    assert result.tasks[0].missing_inputs == ["data_source"]
    assert result.clarification_required is True


def test_generic_external_platform_submit_requires_system_clarification() -> None:
    analyzer = make_analyzer()

    result = analyzer.analyze(
        text="订单状态推回外部平台",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks[0].task_type == "EXTERNAL_SYSTEM_SUBMIT"
    assert result.tasks[0].missing_inputs == ["external_system"]
    assert result.clarification_required is True


def test_policy_wording_counts_as_commission_calculation_policy() -> None:
    analyzer = make_analyzer()

    result = analyzer.analyze(
        text="请按2026年新版提成口径核算华东销售团队上月提成",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    task = result.tasks[0]
    assert task.task_type == "RULE_CALCULATION_COMMISSION"
    assert task.missing_inputs == []
    assert result.clarification_required is False


def test_process_name_and_trigger_condition_are_read_from_plain_business_text() -> None:
    analyzer = make_analyzer()

    workflow = analyzer.analyze(
        text="启动供应商准入流程",
        user_id="user-001",
        conversation_id="conversation-001",
    )
    reminder = analyzer.analyze(
        text="库存低于安全线时提醒运营负责人",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert workflow.tasks[0].task_type == "WORKFLOW_START"
    assert workflow.tasks[0].missing_inputs == []
    assert workflow.clarification_required is False
    assert reminder.tasks[0].task_type == "MONITORING_REMINDER"
    assert reminder.tasks[0].missing_inputs == []
    assert reminder.clarification_required is False


def test_generic_process_phrase_still_requires_process_name() -> None:
    analyzer = make_analyzer()

    result = analyzer.analyze(
        text="办理流程",
        user_id="user-001",
        conversation_id="conversation-001",
    )

    assert result.tasks[0].task_type == "PROCESS_HANDLE"
    assert result.tasks[0].missing_inputs == ["process_name"]
    assert result.clarification_required is True


def test_material_and_specific_analysis_object_reduce_unnecessary_clarification() -> None:
    validator, task_factory = make_validator()
    document = task_factory.create_task(
        task_name="生成业务文档",
        task_type="DOCUMENT_GENERATE",
        required_inputs=[],
        missing_inputs=[],
        dependencies=[],
        execution_order=1,
        confidence=0.9,
    )
    analysis = task_factory.create_task(
        task_name="经营分析",
        task_type="DATA_ANALYSIS_PROBLEM",
        required_inputs=[],
        missing_inputs=[],
        dependencies=[],
        execution_order=1,
        confidence=0.9,
    )

    validated_document = validator.validate_task(document, source_text="经营复盘材料")
    validated_analysis = validator.validate_task(
        analysis,
        source_text="需要判断客户经营质量有没有明显下滑信号",
    )

    assert validated_document.missing_inputs == []
    assert validated_analysis.missing_inputs == []


def test_aggregation_can_inherit_scope_from_upstream_fetch_dependency() -> None:
    validator, task_factory = make_validator()
    fetch = task_factory.create_task(
        task_name="获取CRM客户数据",
        task_type="EXTERNAL_DATA_FETCH",
        required_inputs=["external_system:CRM"],
        missing_inputs=[],
        dependencies=[],
        execution_order=1,
        confidence=0.9,
    )
    aggregation = task_factory.create_task(
        task_name="按风险等级汇总客户",
        task_type="DATA_AGGREGATION_SUMMARY",
        required_inputs=[],
        missing_inputs=[],
        dependencies=[fetch.task_id],
        execution_order=2,
        confidence=0.9,
    )

    validated = validator.validate_task_list([fetch, aggregation])

    assert validated[1].missing_inputs == []
    assert validated[1].clarification_required is False
