from app.services.embedding import BGEProvider, EmbeddingProviderError, EmbeddingService
from app.services.semantic import BGEProvider as SemanticBGEProvider
from app.services.semantic import EmbeddingService as SemanticEmbeddingService


class FakeSentenceTransformer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_sentence_embedding_dimension(self) -> int:
        return 3

    def encode(self, texts: list[str], **kwargs) -> list[list[float]]:
        self.calls.append({"texts": texts, **kwargs})
        return [[3.0, 4.0, 0.0] for _ in texts]


def test_bge_provider_uses_sentence_transformer_model() -> None:
    model = FakeSentenceTransformer()
    provider = BGEProvider(model_name="BAAI/bge-base-zh-v1.5", model=model)

    embeddings = provider.embed(["销售提成"])

    assert provider.model_name == "BAAI/bge-base-zh-v1.5"
    assert provider.dimension == 3
    assert embeddings == [[3.0, 4.0, 0.0]]
    assert model.calls[0]["texts"] == ["销售提成"]
    assert model.calls[0]["normalize_embeddings"] is False


def test_embedding_service_normalizes_vectors() -> None:
    service = EmbeddingService(provider=BGEProvider(model=FakeSentenceTransformer()))

    embedding = service.embed_query("销售提成")

    assert embedding == [0.6, 0.8, 0.0]


def test_semantic_imports_remain_compatible() -> None:
    assert SemanticBGEProvider is BGEProvider
    assert SemanticEmbeddingService is EmbeddingService


def test_embedding_provider_error_exported() -> None:
    assert issubclass(EmbeddingProviderError, RuntimeError)
