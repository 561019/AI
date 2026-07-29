from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from .engine import DocumentTableEngine, ParseRequest
from .contracts import DocumentParseCommand
from .jobs import JobRecord, JobRepository, JobStatus, ReviewDecision
from .models import ParseRoute, ParseStatus
from .object_store import ObjectStore
from .parsers import DIRECT_EXTENSIONS, OCR_EXTENSIONS, OCRProvider
from .security import PermissionPolicy
from .standard_document import StandardDocumentBuilder
from .templates import ParseTemplate


class TemplateCatalog:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def resolve(self, template_id: str | None, version: str | None = None) -> Path | None:
        if not template_id:
            return None
        candidates: list[tuple[ParseTemplate, Path]] = []
        for path in self.root.glob("*.json"):
            template = ParseTemplate.load(path)
            if template.template_id == template_id and (version is None or template.version == version):
                candidates.append((template, path))
        if not candidates:
            raise ValueError(f"模板不存在: {template_id}@{version or 'latest'}")
        candidates.sort(key=lambda item: item[0].version, reverse=True)
        return candidates[0][1].resolve()

    def list(self) -> list[dict[str, str]]:
        items = []
        for path in self.root.glob("*.json"):
            template = ParseTemplate.load(path)
            items.append({
                "template_id": template.template_id,
                "version": template.version,
                "document_type": template.document_type,
            })
        return sorted(items, key=lambda item: (item["template_id"], item["version"]))


class DocumentJobService:
    def __init__(self, repository: JobRepository, object_store: ObjectStore, template_catalog: TemplateCatalog, permission_policy: PermissionPolicy):
        self.repository = repository
        self.object_store = object_store
        self.template_catalog = template_catalog
        self.permission_policy = permission_policy

    async def submit(
        self,
        source: Path,
        original_name: str,
        actor_id: str,
        business_tags: list[str],
        confidence_threshold: float = 0.85,
        template_id: str | None = None,
        template_version: str | None = None,
        platform_envelope: dict[str, Any] | None = None,
        input_key_override: str | None = None,
    ) -> JobRecord:
        if not actor_id.strip():
            raise ValueError("必须提供当前操作真人 actor_id")
        if not business_tags:
            raise ValueError("至少提供一个业务对象标签")
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("confidence_threshold 必须在 0 到 1 之间")
        await asyncio.to_thread(self.permission_policy.require, actor_id, "document:parse", business_tags)
        template_path = self.template_catalog.resolve(template_id, template_version)
        if platform_envelope:
            existing = await self.repository.find_by_idempotency_key(platform_envelope["idempotency_key"])
            if existing:
                return existing
        job_id = uuid.uuid4().hex
        safe_suffix = Path(original_name).suffix.lower()
        if safe_suffix not in DIRECT_EXTENSIONS | OCR_EXTENSIONS:
            raise ValueError(
                f"unsupported file type: {safe_suffix or '(no extension)'}. "
                "Supported: PDF, DOCX, PPTX, XLS/XLSX/XLSM, CSV/TSV, Markdown, JSON, and image files."
            )
        input_key = input_key_override or f"jobs/{job_id}/original{safe_suffix}"
        if not input_key_override:
            await self.object_store.put_file(source, input_key)
        job = JobRecord(
            job_id=job_id,
            status=JobStatus.QUEUED,
            actor_id=actor_id,
            business_tags=business_tags,
            input_key=input_key,
            original_name=Path(original_name).name,
            confidence_threshold=confidence_threshold,
            template_path=str(template_path) if template_path else None,
            options={
                **({"platform_envelope": platform_envelope} if platform_envelope else {}),
            },
        )
        await self.repository.create(job)
        return job

    async def submit_dispatched(self, command: DocumentParseCommand) -> JobRecord:
        artifact = command.context.artifact_refs[0]
        if artifact.resource_type not in {"document", "file", "attachment"}:
            raise ValueError("document.parse 仅接受文件 artifact_ref")
        if "read" not in artifact.allowed_actions:
            raise PermissionDenied("artifact_ref 未授权 read 动作")
        if command.target.layer != "L2":
            raise ValueError("document.parse 目标必须是 L2 服务")
        tags = artifact.data_labels or ["unclassified"]
        await asyncio.to_thread(self.permission_policy.require, command.actor.person_id, "data.read", tags)
        return await self.submit(
            source=Path(artifact.original_name),
            original_name=artifact.original_name,
            actor_id=command.actor.person_id,
            business_tags=tags,
            confidence_threshold=command.confidence_threshold,
            template_id=command.template_id,
            template_version=command.template_version,
            platform_envelope=command.model_dump(mode="json"),
            input_key_override=artifact.storage_key,
        )

    async def review(
        self,
        job_id: str,
        value_id: str,
        reviewer_id: str,
        decision: str,
        corrected_value: Any | None = None,
        note: str | None = None,
    ) -> ReviewDecision:
        if decision not in {"confirm", "correct", "reject"}:
            raise ValueError("decision 必须是 confirm、correct 或 reject")
        if decision == "correct" and corrected_value is None:
            raise ValueError("correct 决策必须提供 corrected_value")
        job = await self.repository.get(job_id)
        if not job or not job.result:
            raise KeyError(job_id)
        value = find_value(job.result, value_id)
        review_ids = set(job.result.get("registration", {}).get("review_value_ids", []))
        if not value or value_id not in review_ids:
            raise ValueError("该字段不存在或无需复核")
        await asyncio.to_thread(self.permission_policy.require, reviewer_id, "human.approve", job.business_tags)
        review = ReviewDecision(
            job_id=job_id,
            value_id=value_id,
            reviewer_id=reviewer_id,
            decision=decision,
            original_value=value.get("raw_value"),
            corrected_value=corrected_value,
            note=note,
        )
        await self.repository.save_review(review)
        return review


class AsyncDocumentWorker:
    def __init__(
        self,
        repository: JobRepository,
        object_store: ObjectStore,
        work_dir: Path,
        ocr_provider: OCRProvider,
        permission_policy: PermissionPolicy,
    ):
        self.repository = repository
        self.object_store = object_store
        self.work_dir = work_dir
        self.ocr_provider = ocr_provider
        self.permission_policy = permission_policy
        self.standard_document_builder = StandardDocumentBuilder()

    async def run_once(self) -> bool:
        job = await self.repository.claim_next()
        if not job:
            return False
        task_dir = self.work_dir / job.job_id
        input_path = task_dir / job.original_name
        try:
            await asyncio.to_thread(self.permission_policy.require, job.actor_id, "data.read", job.business_tags)
            await self.object_store.get_file(job.input_key, input_path)
            if input_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp", ".pdf"}:
                await asyncio.to_thread(self.permission_policy.require, job.actor_id, "model.generate", job.business_tags)
            engine = DocumentTableEngine(task_dir / "three-split", self.permission_policy, self.ocr_provider)
            result = await asyncio.to_thread(engine.parse, ParseRequest(
                file_path=input_path,
                actor_id=job.actor_id,
                business_tags=job.business_tags,
                template_path=Path(job.template_path) if job.template_path else None,
                confidence_threshold=job.confidence_threshold,
                job_id=job.job_id,
            ))
            status = JobStatus.REVIEW_REQUIRED if result.registration.status == ParseStatus.REVIEW_REQUIRED else JobStatus.COMPLETED
            package_root = task_dir / "standard-document" / "v1"
            package = await asyncio.to_thread(
                self.standard_document_builder.build, input_path, result, package_root, job.input_key,
            )
            object_prefix = f"standard-documents/{job.job_id}/v1"
            for package_file in package.files:
                relative = package_file.relative_to(package.root).as_posix()
                await self.object_store.put_file(package_file, f"{object_prefix}/{relative}")
            package_info = {
                "schema": package.manifest["schema"],
                "document_id": package.manifest["document_id"],
                "package_version": package.manifest["package_version"],
                "profile": package.manifest["profile"],
                "status": package.manifest["status"],
                "source_sha256": package.manifest["source"]["sha256"],
                "object_prefix": object_prefix,
                "manifest_key": f"{object_prefix}/manifest.json",
                "document_key": f"{object_prefix}/document.md",
                "blocks_key": f"{object_prefix}/blocks.jsonl",
                "layout_key": f"{object_prefix}/layout.json",
                "access_url": f"/v1/jobs/{job.job_id}/standard-document/manifest.json",
                "file_count": len(package.files),
            }
            await self.repository.register_package(job.job_id, package_info)
            result_payload = result.to_dict()
            result_payload["standard_document"] = package_info
            await self.repository.complete(job.job_id, status, result_payload)
            return True
        except Exception as exc:
            await self.repository.fail(job.job_id, f"{type(exc).__name__}: {exc}")
            return True

    async def run_forever(self, poll_seconds: float = 1.0) -> None:
        while True:
            processed = await self.run_once()
            if not processed:
                await asyncio.sleep(poll_seconds)


def find_value(result: dict[str, Any], value_id: str) -> dict[str, Any] | None:
    semantic = result.get("semantic", {})
    values = [*semantic.get("text_blocks", []), *semantic.get("fields", [])]
    for table in semantic.get("tables", []):
        values.extend(table.get("values", []))
    return next((value for value in values if value.get("value_id") == value_id), None)


def pending_values(job: JobRecord, decisions: list[ReviewDecision]) -> list[dict[str, Any]]:
    if not job.result:
        return []
    reviewed = {decision.value_id for decision in decisions}
    required = set(job.result.get("registration", {}).get("review_value_ids", []))
    semantic = job.result.get("semantic", {})
    values = [*semantic.get("text_blocks", []), *semantic.get("fields", [])]
    for table in semantic.get("tables", []):
        values.extend(table.get("values", []))
    return [value for value in values if value.get("value_id") in required and value.get("value_id") not in reviewed]
