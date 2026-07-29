from unittest.mock import MagicMock

from app.repositories.vector_repository import VectorRepository


class FakeEntity:
    def __init__(self, data: dict) -> None:
        self.data = data

    def get(self, key: str):
        return self.data.get(key)


class FakeHit:
    def __init__(self, entity: dict, score: float) -> None:
        self.entity = FakeEntity(entity)
        self.score = score


def test_vector_repository_insert_flushes_collection() -> None:
    collection = MagicMock()
    collection.insert.return_value = {"insert_count": 1}
    repository = VectorRepository(collection=collection)

    result = repository.insert([{"function_code": "REPORT_CREATE"}])

    assert result == {"insert_count": 1}
    collection.insert.assert_called_once()
    collection.flush.assert_called_once()


def test_vector_repository_search_serializes_milvus_hits() -> None:
    collection = MagicMock()
    collection.search.return_value = [
        [
            FakeHit(
                {
                    "function_code": "REPORT_CREATE",
                    "text": "create report",
                    "metadata": {
                        "function_name": "Report",
                        "intent_category": "report_generation",
                        "target_engine": "report_engine",
                        "source_type": "example_sentence",
                    },
                },
                0.91,
            ),
        ],
    ]
    repository = VectorRepository(collection=collection)

    result = repository.search([0.1, 0.2], top_k=3)

    assert result == [
        {
            "function_code": "REPORT_CREATE",
            "function_name": "Report",
            "intent_category": "report_generation",
            "target_engine": "report_engine",
            "source_type": "example_sentence",
            "text": "create report",
            "source_text": "create report",
            "similarity_score": 0.91,
        },
    ]
    collection.search.assert_called_once()
    assert collection.search.call_args.kwargs["output_fields"] == [
        "function_code",
        "text",
        "metadata",
    ]


def test_vector_repository_delete_flushes_collection() -> None:
    collection = MagicMock()
    collection.delete.return_value = {"delete_count": 1}
    repository = VectorRepository(collection=collection)

    result = repository.delete('function_code == "REPORT_CREATE"')

    assert result == {"delete_count": 1}
    collection.delete.assert_called_once_with('function_code == "REPORT_CREATE"')
    collection.flush.assert_called_once()
