from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .audit import HashChainAuditLog
from .models import OriginalRecord, ParseResult, ParseRoute, ParseStatus, RegistrationRecord
from .parsers import DIRECT_EXTENSIONS, OCR_EXTENSIONS, OCRProvider, SidecarOCRProvider, StructuredParser, media_type
from .security import PermissionPolicy, StaticPermissionPolicy
from .storage import LocalThreeSplitStore
from .templates import ParseTemplate, TemplateExtractor


@dataclass(frozen=True)
class ParseRequest:
    file_path: Path
    actor_id: str
    business_tags: list[str]
    template_path: Path | None = None
    confidence_threshold: float = 0.85
    metadata: dict[str, str] = field(default_factory=dict)
    job_id: str | None = None


class DocumentTableEngine:
    def __init__(
        self,
        output_dir: Path,
        permission_policy: PermissionPolicy | None = None,
        ocr_provider: OCRProvider | None = None,
    ):
        self.output_dir = output_dir
        self.permission_policy = permission_policy or StaticPermissionPolicy()
        self.ocr_provider = ocr_provider or SidecarOCRProvider()
        self.structured_parser = StructuredParser()
        self.template_extractor = TemplateExtractor()
        self.store = LocalThreeSplitStore(output_dir)
        self.audit = HashChainAuditLog(output_dir / "audit" / "events.jsonl")

    def parse(self, request: ParseRequest) -> ParseResult:
        path = request.file_path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if not request.business_tags:
            raise ValueError("至少提供一个业务对象标签")
        if not 0.0 <= request.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold 必须在 0 到 1 之间")

        self.permission_policy.require(request.actor_id, "document:parse", request.business_tags)
        file_hash = self._sha256(path)
        job_id = request.job_id or uuid.uuid4().hex
        self.audit.append("parse.accepted", {
            "job_id": job_id,
            "actor_id": request.actor_id,
            "file_sha256": file_hash,
            "business_tags": request.business_tags,
        })

        try:
            return self._execute(request, path, file_hash, job_id)
        except Exception as exc:
            self.audit.append("parse.failed", {
                "job_id": job_id,
                "actor_id": request.actor_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            raise

    def _execute(self, request: ParseRequest, path: Path, file_hash: str, job_id: str) -> ParseResult:

        template: ParseTemplate | None = None
        if request.template_path:
            template = ParseTemplate.load(request.template_path)

        suffix = path.suffix.lower()
        if suffix in DIRECT_EXTENSIONS:
            content = self.structured_parser.parse(path, file_hash)
            route = ParseRoute.DIRECT
        elif suffix in OCR_EXTENSIONS:
            content = self.ocr_provider.recognize(path, file_hash)
            route = ParseRoute.OCR
        else:
            raise ValueError(f"不支持的文件类型: {suffix}")

        if template:
            content.fields = self.template_extractor.extract(content, template)
            route = ParseRoute.TEMPLATE

        all_values = [*content.text_blocks, *content.fields, *(v for table in content.tables for v in table.values)]
        for index, value in enumerate(all_values):
            if value.confidence_basis == "未标注":
                value.confidence_basis = "原生结构化直读" if route == ParseRoute.DIRECT else "OCR 服务原始置信度"
            identity = f"{job_id}:{index}:{value.source!r}:{value.field_name or ''}"
            value.value_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
            value.needs_review = value.confidence < request.confidence_threshold
            value.auto_fill_allowed = not value.needs_review
        review_candidates = content.fields if template and content.fields else all_values
        review_value_ids = [value.value_id for value in review_candidates if value.needs_review]
        review_count = len(review_value_ids)
        status = ParseStatus.REVIEW_REQUIRED if review_count else ParseStatus.COMPLETED

        result = ParseResult(
            original=OriginalRecord(path.name, media_type(path), path.stat().st_size, file_hash),
            registration=RegistrationRecord(
                job_id=job_id,
                actor_id=request.actor_id,
                business_tags=request.business_tags,
                route=route,
                status=status,
                created_at=datetime.now(UTC).isoformat(),
                template_id=template.template_id if template else None,
                template_version=template.version if template else None,
                review_count=review_count,
                review_value_ids=review_value_ids,
            ),
            semantic=content,
        )
        self.store.save(path, result)
        self.audit.append("parse.completed", {
            "job_id": job_id,
            "actor_id": request.actor_id,
            "status": status,
            "route": route,
            "review_count": review_count,
            "template_version": template.version if template else None,
        })
        return result

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
