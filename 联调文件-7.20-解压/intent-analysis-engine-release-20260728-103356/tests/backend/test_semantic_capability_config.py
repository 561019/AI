from app.services.intent_analysis_engine import FunctionRegistryCatalog
from app.services.semantic import SemanticCapabilityCatalog, build_intent_capability_records


class FakeEmbeddingService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return [float(len(text))]


def test_semantic_capability_catalog_loads_default_yaml() -> None:
    catalog = SemanticCapabilityCatalog.from_default_file()
    capability = catalog.get_by_task_type("RULE_CALCULATION_COMMISSION")

    assert capability is not None
    assert capability.engine_code == "ENG_RULE_CALCULATION"
    assert capability.task_name == "计算销售提成"
    assert "帮我看看销售人员奖金怎么算" in capability.examples
    assert capability.required_inputs == [
        "calculation_policy",
        "sales_data_source",
        "statistical_range",
    ]


def test_build_intent_capability_records_uses_configured_capabilities() -> None:
    embedding_service = FakeEmbeddingService()
    records = build_intent_capability_records(
        registry=FunctionRegistryCatalog(),
        embedding_service=embedding_service,
    )

    commission_record = next(record for record in records if record["task_type"] == "RULE_CALCULATION_COMMISSION")
    assert commission_record["engine_code"] == "ENG_RULE_CALCULATION"
    assert commission_record["keywords"] == ["销售提成", "提成", "佣金", "奖金"]
    assert "帮我算一算销售提成" in commission_record["examples"]
    assert any("RULE_CALCULATION_COMMISSION" in call for call in embedding_service.calls)
    assert commission_record["embedding_vector"]
    assert all(record["task_type"] != "GENERAL_TASK" for record in records)
    assert len(records) == 26
