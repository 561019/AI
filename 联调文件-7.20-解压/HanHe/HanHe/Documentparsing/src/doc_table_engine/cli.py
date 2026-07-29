from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import DocumentTableEngine, ParseRequest
from .security import StaticPermissionPolicy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="可信文档表格解析引擎 MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)
    parse_parser = subparsers.add_parser("parse", help="解析一个文档")
    parse_parser.add_argument("file", type=Path)
    parse_parser.add_argument("--actor-id", required=True)
    parse_parser.add_argument("--business-tag", action="append", required=True, dest="business_tags")
    parse_parser.add_argument("--template", type=Path)
    parse_parser.add_argument("--confidence-threshold", type=float, default=0.85)
    parse_parser.add_argument("--output-dir", type=Path, default=Path("engine-output"))
    verify_parser = subparsers.add_parser("verify-audit", help="校验审计哈希链")
    verify_parser.add_argument("--output-dir", type=Path, default=Path("engine-output"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    policy = StaticPermissionPolicy(allow_demo_actor=True)
    engine = DocumentTableEngine(args.output_dir, permission_policy=policy)
    if args.command == "verify-audit":
        print(json.dumps({"audit_valid": engine.audit.verify()}, ensure_ascii=False))
        return
    result = engine.parse(ParseRequest(
        file_path=args.file,
        actor_id=args.actor_id,
        business_tags=args.business_tags,
        template_path=args.template,
        confidence_threshold=args.confidence_threshold,
    ))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

