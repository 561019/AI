import pytest

from app.services.task_extraction import LongContextTaskExtractionLayer, LongTextParser


def build_document(target_length: int) -> str:
    background = "本段只说明历史情况和沟通安排，不包含需要执行的任务。"
    start_task = "请查询今年销售数据。"
    middle_task = "中间明确要求：请分析销售趋势。"
    end_task = "最后明确要求：请生成销售分析报告。"
    available = target_length - len(start_task) - len(middle_task) - len(end_task)
    first_size = available // 2
    first_background = (background * (first_size // len(background) + 1))[:first_size]
    second_size = available - len(first_background)
    second_background = (background * (second_size // len(background) + 1))[:second_size]
    return start_task + first_background + middle_task + second_background + end_task


@pytest.mark.parametrize("target_length", [20_000, 50_000, 100_000])
def test_long_context_preserves_tasks_across_large_documents(target_length: int) -> None:
    text = build_document(target_length)
    layer = LongContextTaskExtractionLayer(
        parser=LongTextParser(chunk_size=2000, chunk_overlap=200),
        activation_length=1,
    )

    result = layer.extract(text)

    assert len(text) == target_length
    assert result.document.chunks[-1].end == target_length
    assert [candidate.action for candidate in result.merged_candidates] == [
        "query",
        "analyze",
        "generate",
    ]
