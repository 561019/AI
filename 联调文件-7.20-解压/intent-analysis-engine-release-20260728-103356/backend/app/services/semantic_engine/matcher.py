from app.integrations.models.base import BaseModelGateway
from app.repositories.vector_repository import VectorRepository
from app.schemas.semantic import SemanticCandidate, SemanticResult


class SemanticMatcher:
    """Level 2 semantic matcher for candidate function retrieval."""

    def __init__(
        self,
        *,
        model_gateway: BaseModelGateway,
        vector_repository: VectorRepository,
        top_k: int = 5,
        match_threshold: float = 0.50,
    ) -> None:
        self.model_gateway = model_gateway
        self.vector_repository = vector_repository
        self.top_k = top_k
        self.match_threshold = match_threshold

    def analyze(self, text: str) -> SemanticResult:
        if not text or not text.strip():
            return SemanticResult.unmatched()

        embedding = self.embed_text(text)
        raw_candidates = self.search_candidates(embedding)
        candidates = self.rank_candidates(raw_candidates)

        if not candidates:
            return SemanticResult.unmatched()

        if candidates[0].confidence < self.match_threshold:
            return SemanticResult.unmatched(candidates=candidates)

        return SemanticResult.matched_result(candidates=candidates)

    def embed_text(self, text: str) -> list[float]:
        embeddings = self.model_gateway.embedding([text])
        return embeddings[0] if embeddings else []

    def search_candidates(self, embedding: list[float]) -> list[dict]:
        return self.vector_repository.search(embedding, top_k=self.top_k)

    def rank_candidates(self, raw_candidates: list[dict]) -> list[SemanticCandidate]:
        best_by_function: dict[str, SemanticCandidate] = {}

        for raw_candidate in raw_candidates:
            function_code = raw_candidate.get("function_code")
            if not function_code:
                continue

            similarity_score = self._normalize_score(raw_candidate.get("similarity_score", 0))
            candidate = SemanticCandidate(
                function_code=function_code,
                function_name=raw_candidate.get("function_name"),
                intent_category=raw_candidate.get("intent_category"),
                target_engine=raw_candidate.get("target_engine"),
                confidence=self.calculate_confidence(similarity_score),
                similarity_score=similarity_score,
            )

            existing = best_by_function.get(function_code)
            if existing is None or candidate.confidence > existing.confidence:
                best_by_function[function_code] = candidate

        return sorted(
            best_by_function.values(),
            key=lambda candidate: (candidate.confidence, candidate.similarity_score),
            reverse=True,
        )[: self.top_k]

    def calculate_confidence(self, similarity_score: float) -> float:
        return self._normalize_score(similarity_score)

    def _normalize_score(self, value: float | int | str | None) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0

        return max(0, min(score, 1))
