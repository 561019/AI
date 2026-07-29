from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import Settings
from .models import SearchRequest
from .runtime import build_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HanHe Milvus retrieval and SiliconFlow reranking")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="optional KEY=VALUE environment file")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("check", help="validate configuration and the existing Milvus collection")
    search = commands.add_parser("search", help="retrieve candidates and rerank them")
    search.add_argument("query")
    search.add_argument("--actor-id", default="demo-user")
    search.add_argument("--candidate-k", type=int)
    search.add_argument("--top-n", type=int)
    search.add_argument("--document-id", action="append", default=[])
    search.add_argument("--business-tag", action="append", required=True)
    search.add_argument("--include-review-required", action="store_true")
    search.add_argument("--min-vector-score", type=float)
    search.add_argument("--min-rerank-score", type=float)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    _load_env(args.env_file)
    settings = Settings.from_env()
    service = build_service(settings)
    try:
        if args.command == "check":
            _print({
                "status": "ok",
                "collection": settings.milvus_collection,
                "embedding_model": settings.embedding_model,
                "embedding_dimensions": settings.embedding_dimensions,
                "rerank_model": settings.rerank_model,
            })
            return
        request = SearchRequest(
            query=args.query,
            candidate_k=args.candidate_k or settings.default_candidate_k,
            top_n=args.top_n or settings.default_top_n,
            document_ids=args.document_id,
            business_tags=args.business_tag,
            include_review_required=args.include_review_required,
            min_vector_score=args.min_vector_score,
            min_rerank_score=args.min_rerank_score,
        )
        _print(service.search(args.actor_id, request).model_dump(mode="json", by_alias=True))
    finally:
        service.close()


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
