from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.embedding.base import EmbeddingProviderError


class BGEProvider:
    """SentenceTransformers-backed BGE embedding provider."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        device: str | None = None,
        cache_folder: str | None = None,
        local_files_only: bool | None = None,
        batch_size: int = 32,
        model: Any | None = None,
    ) -> None:
        self.model_name = model_name or settings.embedding_model_name
        self.device = device
        self.cache_folder = cache_folder
        self.local_files_only = settings.embedding_local_files_only if local_files_only is None else local_files_only
        self.batch_size = batch_size
        self._model = model

    @property
    def dimension(self) -> int | None:
        model = self._load_model()
        if hasattr(model, "get_embedding_dimension"):
            dimension = model.get_embedding_dimension()
            return int(dimension) if dimension is not None else None
        if hasattr(model, "get_sentence_embedding_dimension"):
            dimension = model.get_sentence_embedding_dimension()
            return int(dimension) if dimension is not None else None
        return None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        model = self._load_model()
        prepared_texts = [self._prepare_text(text) for text in texts]
        try:
            embeddings = model.encode(
                prepared_texts,
                batch_size=self.batch_size,
                convert_to_numpy=True,
                normalize_embeddings=False,
                show_progress_bar=False,
            )
        except Exception as error:
            raise EmbeddingProviderError(f"BGE embedding failed for model {self.model_name!r}.") from error

        return [self._to_float_list(embedding) for embedding in embeddings]

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ModuleNotFoundError as error:
            raise EmbeddingProviderError(
                "sentence-transformers is required for real BGE embeddings. "
                "Install backend dependencies before generating intent capability vectors.",
            ) from error

        try:
            self._model = SentenceTransformer(
                self.model_name,
                device=self.device,
                cache_folder=self.cache_folder,
                local_files_only=self.local_files_only,
            )
        except Exception as error:
            raise EmbeddingProviderError(f"Failed to load embedding model {self.model_name!r}.") from error
        return self._model

    def _prepare_text(self, text: str) -> str:
        value = str(text or "").strip()
        return value or " "

    def _to_float_list(self, values: Any) -> list[float]:
        if hasattr(values, "tolist"):
            values = values.tolist()
        if not isinstance(values, list):
            raise EmbeddingProviderError("Embedding value must be list-like.")
        try:
            return [float(value) for value in values]
        except (TypeError, ValueError) as error:
            raise EmbeddingProviderError("Embedding value contains non-numeric items.") from error
