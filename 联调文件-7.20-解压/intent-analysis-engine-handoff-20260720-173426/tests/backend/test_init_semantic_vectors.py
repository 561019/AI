from app.models import FunctionRegistry
from app.scripts.init_semantic_vectors import build_vector_records


class FakeModelGateway:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embedding(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(len(text))] for text in texts]

    def rerank(self, query: str, candidates: list[str | dict]) -> list[dict]:
        return []

    def chat(self, messages: list[dict[str, str]]) -> str:
        return ""


def test_build_vector_records_uses_function_registry_fields() -> None:
    function = FunctionRegistry(
        function_code="REPORT_CREATE",
        function_name="Report Generation",
        intent_category="report_generation",
        target_engine="report_engine",
        description="Create report from clear data.",
        required_parameters={},
        example_sentences=["create report", "summarize operations"],
        status="active",
    )
    model_gateway = FakeModelGateway()

    records = build_vector_records(
        model_gateway=model_gateway,
        functions=[function],
    )

    assert len(records) == 4
    assert [record["metadata"]["source_type"] for record in records] == [
        "function_name",
        "description",
        "example_sentence",
        "example_sentence",
    ]
    assert records[0]["function_code"] == "REPORT_CREATE"
    assert records[0]["text"] == "Report Generation"
    assert records[0]["metadata"]["target_engine"] == "report_engine"
    assert records[0]["metadata"]["source_text"] == "Report Generation"
    assert records[0]["embedding"] == [17.0]
    assert model_gateway.calls == [
        ["Report Generation"],
        ["Create report from clear data."],
        ["create report"],
        ["summarize operations"],
    ]


def test_build_vector_records_skips_empty_source_texts() -> None:
    function = FunctionRegistry(
        function_code="DATA_QUERY",
        function_name="Data Query",
        intent_category="intelligent_qa",
        target_engine="knowledge_qa_engine",
        description="",
        required_parameters={},
        example_sentences=["", "query data"],
        status="active",
    )
    model_gateway = FakeModelGateway()

    records = build_vector_records(
        model_gateway=model_gateway,
        functions=[function],
    )

    assert len(records) == 2
    assert [record["text"] for record in records] == ["Data Query", "query data"]
    assert [record["metadata"]["source_text"] for record in records] == ["Data Query", "query data"]
