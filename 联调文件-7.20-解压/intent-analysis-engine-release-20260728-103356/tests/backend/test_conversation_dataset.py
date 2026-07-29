import json
from collections import Counter
from pathlib import Path


DATASET_PATH = Path(__file__).resolve().parents[2] / "evaluation" / "conversation_dataset.json"
REQUIRED_CATEGORIES = {
    "长文本请求",
    "口语表达",
    "背景信息",
    "多任务请求",
    "多轮上下文",
    "指代表达",
    "无效信息干扰",
}


def load_dataset() -> list[dict]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def test_conversation_dataset_contains_100_unique_cases() -> None:
    dataset = load_dataset()

    assert len(dataset) >= 100
    assert len({case["id"] for case in dataset}) == len(dataset)


def test_conversation_dataset_covers_all_required_categories() -> None:
    dataset = load_dataset()
    categories = Counter(case["category"] for case in dataset)

    assert REQUIRED_CATEGORIES <= set(categories)
    assert all(categories[category] >= 10 for category in REQUIRED_CATEGORIES)


def test_conversation_dataset_schema_is_consistent() -> None:
    for case in load_dataset():
        assert case["conversation"]
        assert all(message["role"] in {"user", "assistant"} for message in case["conversation"])
        assert all(message["text"].strip() for message in case["conversation"])
        assert isinstance(case["expected_tasks"], list)
        assert isinstance(case["should_clarify"], bool)
