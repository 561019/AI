from app.db.base import Base
from app.models import ConversationMessage, FunctionRegistry, IntentRecord, RuleMapping


def test_core_database_tables_are_registered() -> None:
    assert "function_registry" in Base.metadata.tables
    assert "rule_mapping" in Base.metadata.tables
    assert "intent_record" in Base.metadata.tables
    assert "conversation_message" in Base.metadata.tables


def test_function_registry_columns_match_database_design() -> None:
    columns = set(FunctionRegistry.__table__.columns.keys())

    assert columns == {
        "id",
        "function_code",
        "function_name",
        "intent_category",
        "target_engine",
        "description",
        "required_parameters",
        "example_sentences",
        "status",
        "created_at",
        "updated_at",
    }


def test_rule_mapping_columns_match_database_design() -> None:
    columns = set(RuleMapping.__table__.columns.keys())

    assert columns == {
        "id",
        "keyword",
        "pattern",
        "function_code",
        "priority",
        "status",
        "created_at",
    }


def test_intent_record_columns_match_database_design() -> None:
    columns = set(IntentRecord.__table__.columns.keys())

    assert columns == {
        "id",
        "request_text",
        "user_id",
        "conversation_id",
        "analysis_level",
        "matched_function",
        "confidence",
        "result",
        "cost_time",
        "created_at",
    }


def test_database_relationship_keys() -> None:
    rule_fk = next(iter(RuleMapping.__table__.c.function_code.foreign_keys))
    record_fk = next(iter(IntentRecord.__table__.c.matched_function.foreign_keys))

    assert rule_fk.target_fullname == "function_registry.function_code"
    assert record_fk.target_fullname == "function_registry.function_code"


def test_conversation_message_columns_match_state_store_design() -> None:
    columns = set(ConversationMessage.__table__.columns.keys())

    assert columns == {
        "id",
        "conversation_id",
        "user_id",
        "role",
        "content",
        "analysis_result",
        "created_at",
    }
