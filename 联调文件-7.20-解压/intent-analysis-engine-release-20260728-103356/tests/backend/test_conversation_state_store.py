from unittest.mock import MagicMock

from app.models import ConversationMessage
from app.repositories.conversation_state_repository import ConversationStateRepository
from app.services.conversation_understanding import (
    ConversationUnderstandingLayer,
    InMemoryConversationStateStore,
)
from app.services.intent_analysis_engine import FunctionRegistryCatalog, StandardIntentAnalyzer


def make_layer(store: InMemoryConversationStateStore, *, history_limit: int = 20) -> ConversationUnderstandingLayer:
    return ConversationUnderstandingLayer(
        StandardIntentAnalyzer(
            registry=FunctionRegistryCatalog(),
            semantic_matcher=None,
            llm_analyzer=None,
            intent_record_service=None,
        ),
        state_store=store,
        history_limit=history_limit,
    )


def test_in_memory_store_isolates_users_and_conversations() -> None:
    store = InMemoryConversationStateStore()
    store.append_turn(
        conversation_id="conversation-1",
        user_id="user-1",
        text="分析销售数据",
        analysis_result=None,
    )

    assert len(store.load_history(conversation_id="conversation-1", user_id="user-1", limit=20)) == 1
    assert store.load_history(conversation_id="conversation-1", user_id="user-2", limit=20) == []
    assert store.load_history(conversation_id="conversation-2", user_id="user-1", limit=20) == []


def test_state_store_applies_history_limit() -> None:
    store = InMemoryConversationStateStore()
    for index in range(5):
        store.append_turn(
            conversation_id="conversation-1",
            user_id="user-1",
            text=f"message-{index}",
            analysis_result=None,
        )

    history = store.load_history(conversation_id="conversation-1", user_id="user-1", limit=2)
    assert [item.text for item in history] == ["message-3", "message-4"]


def test_second_turn_uses_server_history_without_explicit_history() -> None:
    store = InMemoryConversationStateStore()
    layer = make_layer(store)

    layer.analyze(
        text="帮我分析销售数据",
        user_id="user-1",
        conversation_id="conversation-1",
    )
    second = layer.analyze_with_debug(
        text="继续",
        user_id="user-1",
        conversation_id="conversation-1",
    )

    assert second.debug["conversation_understanding"]["resolved_text"] == "继续分析销售数据"
    assert second.debug["conversation_state"]["stored_history_count"] == 1
    assert second.result.tasks[0].task_type == "DATA_ANALYSIS_PROBLEM"


def test_explicit_and_stored_history_are_deduplicated() -> None:
    store = InMemoryConversationStateStore()
    store.append_turn(
        conversation_id="conversation-1",
        user_id="user-1",
        text="分析销售数据",
        analysis_result=None,
    )
    analysis = make_layer(store).analyze_with_debug(
        text="继续",
        user_id="user-1",
        conversation_id="conversation-1",
        history=[{"role": "user", "text": "分析销售数据"}],
    )

    assert analysis.debug["conversation_state"]["stored_history_count"] == 1
    assert analysis.debug["conversation_state"]["explicit_history_count"] == 1
    assert analysis.debug["conversation_state"]["combined_history_count"] == 1


def test_postgres_repository_appends_message() -> None:
    session = MagicMock()
    repository = ConversationStateRepository(session)
    message = ConversationMessage(
        conversation_id="conversation-1",
        user_id="user-1",
        role="user",
        content="分析销售数据",
    )

    result = repository.append_message(message)

    assert result is message
    session.add.assert_called_once_with(message)
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(message)


def test_postgres_repository_rolls_back_failed_append() -> None:
    session = MagicMock()
    session.commit.side_effect = RuntimeError("database unavailable")
    repository = ConversationStateRepository(session)
    message = ConversationMessage(
        conversation_id="conversation-1",
        user_id="user-1",
        role="user",
        content="分析销售数据",
    )

    try:
        repository.append_message(message)
    except RuntimeError as error:
        assert str(error) == "database unavailable"
    else:
        raise AssertionError("Expected append_message to propagate commit failure")

    session.rollback.assert_called_once()


def test_postgres_repository_returns_recent_messages_in_chronological_order() -> None:
    session = MagicMock()
    newest = ConversationMessage(conversation_id="c", user_id="u", role="user", content="newest")
    oldest = ConversationMessage(conversation_id="c", user_id="u", role="user", content="oldest")
    scalar_result = MagicMock()
    scalar_result.all.return_value = [newest, oldest]
    session.scalars.return_value = scalar_result

    result = ConversationStateRepository(session).list_recent(
        conversation_id="c",
        user_id="u",
        limit=2,
    )

    assert [message.content for message in result] == ["oldest", "newest"]
    session.scalars.assert_called_once()
