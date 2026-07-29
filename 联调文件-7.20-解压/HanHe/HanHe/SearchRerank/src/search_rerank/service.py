from __future__ import annotations

import time
import uuid
from typing import Any

from .embedding import QueryEmbedder
from .milvus import RetrievedChunk, Retriever
from .models import SearchHit, SearchRequest, SearchResponse
from .reranker import Reranker
from .security import PermissionPolicy


class SearchService:
    def __init__(
        self,
        embedder: QueryEmbedder,
        retriever: Retriever,
        reranker: Reranker,
        permission_policy: PermissionPolicy,
        max_candidate_k: int,
    ):
        self.embedder = embedder
        self.retriever = retriever
        self.reranker = reranker
        self.permission_policy = permission_policy
        self.max_candidate_k = max_candidate_k

    def search(self, actor_id: str, request: SearchRequest) -> SearchResponse:
        if request.candidate_k > self.max_candidate_k:
            raise ValueError(f"candidate_k cannot exceed configured limit {self.max_candidate_k}")
        self.permission_policy.require(actor_id, "artifact.read", request.business_tags)
        if request.include_review_required:
            self.permission_policy.require(actor_id, "human.approve", request.business_tags)

        started = time.perf_counter()
        embedding_started = time.perf_counter()
        vector = self.embedder.embed_query(request.query)
        embedding_ms = self._elapsed(embedding_started)

        retrieval_started = time.perf_counter()
        candidates = self.retriever.search(
            vector=vector,
            candidate_k=request.candidate_k,
            document_ids=request.document_ids,
            business_tags=request.business_tags,
            include_review_required=request.include_review_required,
            max_candidate_k=self.max_candidate_k,
        )
        if request.min_vector_score is not None:
            candidates = [item for item in candidates if item.vector_score >= request.min_vector_score]
        retrieval_ms = self._elapsed(retrieval_started)

        rerank_started = time.perf_counter()
        reranked = self.reranker.rerank(
            request.query,
            [item.text for item in candidates],
            min(request.top_n, len(candidates)),
        ) if candidates else []
        if request.min_rerank_score is not None:
            reranked = [item for item in reranked if item.score >= request.min_rerank_score]
        rerank_ms = self._elapsed(rerank_started)

        hits = [
            self._to_hit(rank, candidates[result.index], result.score)
            for rank, result in enumerate(reranked, start=1)
        ]
        return SearchResponse(
            request_id=uuid.uuid4().hex,
            query=request.query,
            embedding_model=self.embedder.model,
            rerank_model=self.reranker.model,
            collection=self.retriever.collection_name,
            candidate_count=len(candidates),
            result_count=len(hits),
            elapsed_ms={
                "embedding": embedding_ms,
                "retrieval": retrieval_ms,
                "rerank": rerank_ms,
                "total": self._elapsed(started),
            },
            items=hits,
        )

    def close(self) -> None:
        self.embedder.close()
        self.reranker.close()
        self.retriever.close()

    @staticmethod
    def _to_hit(rank: int, chunk: RetrievedChunk, rerank_score: float) -> SearchHit:
        metadata = chunk.metadata
        document_base = f"/v1/jobs/{chunk.document_id}"
        return SearchHit(
            rank=rank,
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            package_version=chunk.package_version,
            chunk_index=chunk.chunk_index,
            chunk_type=chunk.chunk_type,
            text=chunk.text,
            vector_score=chunk.vector_score,
            rerank_score=rerank_score,
            needs_review=chunk.needs_review,
            source_sha256=chunk.source_sha256,
            business_tags=SearchService._string_list(metadata.get("business_tags")),
            page_start=SearchService._optional_int(metadata.get("page_start")),
            page_end=SearchService._optional_int(metadata.get("page_end")),
            source_block_ids=SearchService._string_list(metadata.get("source_block_ids")),
            source_refs=SearchService._dict_list(metadata.get("source_refs")),
            asset_refs=SearchService._string_list(metadata.get("asset_refs")),
            references={
                "original": f"{document_base}/original",
                "result": f"{document_base}/result",
                "blocks": f"{document_base}/standard-document/blocks.jsonl",
            },
        )

    @staticmethod
    def _elapsed(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        return [str(item) for item in value] if isinstance(value, list) else []

    @staticmethod
    def _dict_list(value: Any) -> list[dict[str, Any]]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
