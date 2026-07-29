from unittest.mock import MagicMock

from app.models import IntentRecord
from app.repositories.intent_record_repository import IntentRecordRepository


def make_record(record_id: str | None = None, user_id: str = "user-1", level: str = "1") -> IntentRecord:
    record = IntentRecord(
        request_text="生成销售报告",
        user_id=user_id,
        conversation_id="conversation-1",
        analysis_level=level,
        matched_function="REPORT_CREATE",
        confidence=1.0,
        result="success",
        cost_time=12,
    )
    if record_id is not None:
        record.id = record_id
    return record


def mock_scalar_list(session: MagicMock, records: list[IntentRecord]) -> None:
    scalar_result = MagicMock()
    scalar_result.all.return_value = records
    session.scalars.return_value = scalar_result


def test_create_record_persists_intent_record() -> None:
    session = MagicMock()
    record = make_record()
    repository = IntentRecordRepository(session)

    result = repository.create_record(record)

    assert result is record
    session.add.assert_called_once_with(record)
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(record)


def test_create_record_rolls_back_failed_transaction() -> None:
    session = MagicMock()
    session.commit.side_effect = RuntimeError("constraint violation")
    repository = IntentRecordRepository(session)

    try:
        repository.create_record(make_record())
    except RuntimeError as error:
        assert str(error) == "constraint violation"
    else:
        raise AssertionError("Expected create_record to propagate commit failure")

    session.rollback.assert_called_once()


def test_get_by_id_returns_record() -> None:
    session = MagicMock()
    record = make_record(record_id="record-1")
    session.scalar.return_value = record
    repository = IntentRecordRepository(session)

    result = repository.get_by_id("record-1")

    assert result is record
    session.scalar.assert_called_once()


def test_list_records_returns_recent_records() -> None:
    session = MagicMock()
    records = [make_record(record_id="record-1"), make_record(record_id="record-2")]
    mock_scalar_list(session, records)
    repository = IntentRecordRepository(session)

    result = repository.list_records(limit=20, offset=5)

    assert result == records
    session.scalars.assert_called_once()


def test_query_by_user_returns_user_records() -> None:
    session = MagicMock()
    records = [make_record(user_id="user-2")]
    mock_scalar_list(session, records)
    repository = IntentRecordRepository(session)

    result = repository.query_by_user("user-2")

    assert result == records
    session.scalars.assert_called_once()


def test_query_by_level_accepts_integer_level() -> None:
    session = MagicMock()
    records = [make_record(level="1")]
    mock_scalar_list(session, records)
    repository = IntentRecordRepository(session)

    result = repository.query_by_level(1)

    assert result == records
    session.scalars.assert_called_once()


def test_query_by_level_accepts_string_level() -> None:
    session = MagicMock()
    records = [make_record(level="2")]
    mock_scalar_list(session, records)
    repository = IntentRecordRepository(session)

    result = repository.query_by_level("2")

    assert result == records
    session.scalars.assert_called_once()
