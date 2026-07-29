from __future__ import annotations

from .config import Settings
from .embedding import SiliconFlowQueryEmbedder
from .milvus import MilvusRetriever
from .reranker import SiliconFlowReranker
from .security import PermissionPolicy
from .service import SearchService


def build_service(settings: Settings) -> SearchService:
    embedder = SiliconFlowQueryEmbedder(
        api_key=settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        timeout_seconds=settings.embedding_timeout_seconds,
        max_retries=settings.embedding_max_retries,
        query_instruction=settings.query_instruction,
    )
    reranker = SiliconFlowReranker(
        api_key=settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url,
        model=settings.rerank_model,
        instruction=settings.rerank_instruction,
        timeout_seconds=settings.rerank_timeout_seconds,
        max_retries=settings.rerank_max_retries,
    )
    retriever = MilvusRetriever(
        uri=settings.milvus_uri,
        collection_name=settings.milvus_collection,
        token=settings.milvus_token,
        database=settings.milvus_database,
    )
    try:
        retriever.ensure_collection(settings.embedding_dimensions)
    except Exception:
        embedder.close()
        reranker.close()
        retriever.close()
        raise
    return SearchService(
        embedder=embedder,
        retriever=retriever,
        reranker=reranker,
        permission_policy=PermissionPolicy(
            endpoint=settings.permission_api_url,
            api_key=settings.permission_api_key,
            allow_demo_actor=settings.allow_demo_actor,
        ),
        max_candidate_k=settings.max_candidate_k,
    )
