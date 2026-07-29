from types import SimpleNamespace

from scripts.init_semantic_vectors import (
    build_function_code_filter,
    build_semantic_text,
    build_vector_record,
    initialize_semantic_vectors,
)


class FakeModelGateway:
    def __init__(self, *, fail_codes: set[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_codes = fail_codes or set()

    def embedding(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        text = texts[0]
        for code in self.fail_codes:
            if code in text:
                raise RuntimeError(f"embedding failed for {code}")
        return [[float(len(text)), 1.0]]

    def rerank(self, query: str, candidates: list[str | dict]) -> list[dict]:
        return []

    def chat(self, messages: list[dict[str, str]]) -> str:
        return ""


class FakeVectorRepository:
    def __init__(self) -> None:
        self.delete_calls: list[str] = []
        self.insert_calls: list[list[dict]] = []

    def delete(self, filter_expr: str) -> dict:
        self.delete_calls.append(filter_expr)
        return {"delete_count": 1}

    def insert(self, records: list[dict]) -> dict:
        self.insert_calls.append(records)
        return {"insert_count": len(records)}


def make_function(function_code: str = "FUNC_REPORT_GENERATION") -> SimpleNamespace:
    return SimpleNamespace(
        function_code=function_code,
        function_name="经营分析报告生成",
        intent_category="报告生成型",
        target_engine="内容产出引擎",
        description="根据经营数据生成分析报告。",
        example_sentences=["帮我整理经营情况", "生成经营分析报告"],
        status="active",
    )


def test_build_semantic_text_concatenates_registry_fields() -> None:
    text = build_semantic_text(make_function())

    assert "功能名称：经营分析报告生成" in text
    assert "功能描述：根据经营数据生成分析报告。" in text
    assert "示例语句：帮我整理经营情况；生成经营分析报告" in text


def test_build_vector_record_matches_intent_vectors_schema() -> None:
    function = make_function()
    text = build_semantic_text(function)
    record = build_vector_record(function=function, text=text, embedding=[0.1, 0.2])

    assert set(record) == {"function_code", "text", "embedding", "metadata"}
    assert record["function_code"] == "FUNC_REPORT_GENERATION"
    assert record["text"] == text
    assert record["embedding"] == [0.1, 0.2]
    assert record["metadata"]["function_name"] == "经营分析报告生成"
    assert record["metadata"]["example_sentences"] == ["帮我整理经营情况", "生成经营分析报告"]


def test_initialize_semantic_vectors_updates_existing_function_codes() -> None:
    functions = [make_function("FUNC_REPORT_GENERATION"), make_function("FUNC_DATA_QUERY")]
    gateway = FakeModelGateway()
    repository = FakeVectorRepository()

    result = initialize_semantic_vectors(
        functions=functions,
        model_gateway=gateway,
        vector_repository=repository,
    )

    assert result["processed_count"] == 2
    assert result["success_count"] == 2
    assert result["failure_count"] == 0
    assert result["failures"] == []
    assert repository.delete_calls == [
        'function_code == "FUNC_REPORT_GENERATION"',
        'function_code == "FUNC_DATA_QUERY"',
    ]
    assert len(repository.insert_calls) == 2
    assert repository.insert_calls[0][0]["function_code"] == "FUNC_REPORT_GENERATION"
    assert gateway.calls == [
        [build_semantic_text(functions[0])],
        [build_semantic_text(functions[1])],
    ]


def test_initialize_semantic_vectors_counts_failures_and_continues() -> None:
    functions = [make_function("FUNC_OK"), make_function("FUNC_FAIL")]
    functions[1].function_name = "FUNC_FAIL"
    gateway = FakeModelGateway(fail_codes={"FUNC_FAIL"})
    repository = FakeVectorRepository()

    result = initialize_semantic_vectors(
        functions=functions,
        model_gateway=gateway,
        vector_repository=repository,
    )

    assert result["processed_count"] == 2
    assert result["success_count"] == 1
    assert result["failure_count"] == 1
    assert result["failures"][0]["function_code"] == "FUNC_FAIL"
    assert repository.delete_calls == ['function_code == "FUNC_OK"']
    assert len(repository.insert_calls) == 1


def test_build_function_code_filter_escapes_quotes() -> None:
    assert build_function_code_filter('FUNC_"REPORT"') == 'function_code == "FUNC_\\"REPORT\\""'
