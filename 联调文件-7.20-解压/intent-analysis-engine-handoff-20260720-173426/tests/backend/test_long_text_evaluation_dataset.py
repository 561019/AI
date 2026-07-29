import json
from collections import Counter
from pathlib import Path


DATASET_PATH = Path(__file__).parents[2] / "evaluation" / "long_text_dataset.json"


def load_dataset() -> list[dict[str, object]]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def test_long_text_dataset_has_at_least_100_unique_cases() -> None:
    cases = load_dataset()
    identifiers = [case["id"] for case in cases]

    assert len(cases) >= 100
    assert len(identifiers) == len(set(identifiers))


def test_long_text_dataset_covers_all_required_categories() -> None:
    counts = Counter(case["category"] for case in load_dataset())

    assert counts == {
        "业务邮件": 20,
        "会议纪要": 20,
        "用户需求描述": 20,
        "聊天记录": 20,
        "大量背景文本": 20,
    }


def test_long_text_dataset_expected_arrays_are_aligned() -> None:
    for case in load_dataset():
        assert case["text"].strip()
        assert len(case["expected_actions"]) == len(case["expected_tasks"])
        assert isinstance(case["should_clarify"], bool)
