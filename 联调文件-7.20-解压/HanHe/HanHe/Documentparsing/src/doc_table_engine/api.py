from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import tempfile
import zipfile
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings
from .contracts import DocumentParseCommand, PlatformReply, ServiceAddress
from .jobs import JobStatus
from .runtime import Runtime, build_runtime
from .security import PermissionDenied
from .service import pending_values

logger = logging.getLogger("uvicorn.error")


class ReviewBody(BaseModel):
    decision: str
    corrected_value: Any | None = None
    note: str | None = None


def create_app(settings: Settings | None = None, runtime: Runtime | None = None):
    active_runtime = runtime or build_runtime(settings)
    worker_task: asyncio.Task | None = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal worker_task
        await active_runtime.initialize()
        app.state.runtime = active_runtime
        logger.info("服务已就绪，请在浏览器打开：http://localhost:8000/")
        if active_runtime.settings.enable_embedded_worker:
            worker_task = asyncio.create_task(
                active_runtime.worker.run_forever(active_runtime.settings.worker_poll_seconds)
            )
        try:
            yield
        finally:
            if worker_task:
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass
            await active_runtime.close()

    app = FastAPI(
        title="文档表格解析引擎 API",
        version="0.2.0",
        description="异步解析、来源追踪、人工复核、PostgreSQL 与对象存储接口",
        lifespan=lifespan,
    )
    web_root = Path(__file__).resolve().parents[2] / "webui"
    if web_root.is_dir():
        app.mount("/ui", StaticFiles(directory=web_root), name="ui")

    @app.get("/", include_in_schema=False)
    async def console():
        if (web_root / "index.html").is_file():
            return FileResponse(web_root / "index.html")
        return {
            "service": "l2.document_table_parse",
            "capability_id": "CAP.DOCUMENT.PARSE",
            "status": "ready",
            "api_docs": "/docs",
            "health": "/health",
        }

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/v1/templates")
    async def list_templates():
        return {"items": active_runtime.templates.list()}

    @app.post("/v1/platform/document-parse", status_code=202, response_model=PlatformReply)
    async def dispatch_document_parse(command: DocumentParseCommand):
        """L2 internal entry: accept an authorized task plus an artifact reference."""
        try:
            job = await active_runtime.job_service.submit_dispatched(command)
            return PlatformReply(
                reply_type="accepted",
                trace_id=command.trace_id,
                request_id=command.request_id,
                parent_message_id=command.message_id,
                source=ServiceAddress(layer="L2", service_code="l2.document_table_parse"),
                target=command.source,
                task_id=command.context.task_id,
                status=job.status,
                data={"job_id": job.job_id, "status_query": f"/v1/platform/document-parse/{job.job_id}"},
            )
        except PermissionDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/v1/platform/document-parse/{job_id}", response_model=PlatformReply)
    async def get_platform_parse_reply(job_id: str, x_actor_id: str = Header(..., alias="X-Actor-ID")):
        job = await active_runtime.repository.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        envelope = job.options.get("platform_envelope")
        if not envelope:
            raise HTTPException(409, "该任务由兼容上传入口创建，不具备平台信封")
        command = DocumentParseCommand.model_validate(envelope)
        if x_actor_id != command.actor.person_id:
            raise HTTPException(403, "当前真人与任务发起人不一致")
        try:
            await asyncio.to_thread(active_runtime.job_service.permission_policy.require, x_actor_id, "artifact.read", job.business_tags)
        except PermissionDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return PlatformReply(
                reply_type="accepted", trace_id=command.trace_id, request_id=command.request_id,
                parent_message_id=command.message_id, source=command.target, target=command.source,
                task_id=command.context.task_id, status=job.status, data={"job_id": job.job_id},
            )
        if job.status == JobStatus.FAILED:
            return PlatformReply(
                reply_type="failed", trace_id=command.trace_id, request_id=command.request_id,
                parent_message_id=command.message_id, source=command.target, target=command.source,
                task_id=command.context.task_id, status=job.status,
                error={"code": "DOCUMENT_PARSE_FAILED", "message": job.error or "文档解析失败", "retryable": job.attempt_count < 3},
            )
        return PlatformReply(
            reply_type="success", trace_id=command.trace_id, request_id=command.request_id,
            parent_message_id=command.message_id, source=command.target, target=command.source,
            task_id=command.context.task_id, status=job.status,
            data={
                "job_id": job.job_id,
                "result_ref": f"document-result:{job.job_id}",
                "standard_document": (job.result or {}).get("standard_document"),
                "review_required": job.status == JobStatus.REVIEW_REQUIRED,
            },
        )

    @app.post("/v1/jobs", status_code=202)
    async def create_job(
        file: UploadFile = File(...),
        business_tags: str = Form(..., description='JSON 数组，如 ["project:demo"]'),
        confidence_threshold: float = Form(0.85),
        template_id: str | None = Form(None),
        template_version: str | None = Form(None),
        x_actor_id: str = Header(..., alias="X-Actor-ID"),
    ):
        try:
            tags = json.loads(business_tags)
            if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
                raise ValueError("business_tags 必须是字符串数组")
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        temp_root = active_runtime.settings.local_data_dir / "uploads"
        temp_root.mkdir(parents=True, exist_ok=True)
        suffix = Path(file.filename or "upload.bin").suffix
        temp_path: Path | None = None
        uploaded_bytes = 0
        try:
            with tempfile.NamedTemporaryFile(delete=False, dir=temp_root, suffix=suffix) as handle:
                temp_path = Path(handle.name)
                while chunk := await file.read(1024 * 1024):
                    uploaded_bytes += len(chunk)
                    if uploaded_bytes > active_runtime.settings.max_upload_bytes:
                        raise ValueError(f"文件超过上传限制 {active_runtime.settings.max_upload_bytes} 字节")
                    handle.write(chunk)
            job = await active_runtime.job_service.submit(
                temp_path, file.filename or "upload.bin", x_actor_id, tags,
                confidence_threshold, template_id, template_version,
            )
            return {"job_id": job.job_id, "status": job.status, "status_url": f"/v1/jobs/{job.job_id}"}
        except PermissionDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            await file.close()
            if temp_path and temp_path.exists():
                temp_path.unlink()

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str):
        job = await active_runtime.repository.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        payload = asdict(job)
        payload.pop("result", None)
        return payload

    @app.get("/v1/jobs/{job_id}/result")
    async def get_result(job_id: str, x_actor_id: str = Header(..., alias="X-Actor-ID")):
        job = await active_runtime.repository.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            raise HTTPException(409, "任务尚未完成")
        if job.status == JobStatus.FAILED:
            raise HTTPException(422, job.error or "解析失败")
        try:
            await asyncio.to_thread(active_runtime.job_service.permission_policy.require, x_actor_id, "artifact.read", job.business_tags)
        except PermissionDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        reviews = await active_runtime.repository.reviews_for_job(job_id)
        return {"result": job.result, "reviews": [asdict(review) for review in reviews]}

    @app.get("/v1/jobs/{job_id}/original")
    async def get_original(
        job_id: str,
        x_actor_id: str = Header(..., alias="X-Actor-ID"),
    ):
        """Return the stored original only after the same tag-level permission check."""
        job = await active_runtime.repository.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        try:
            await asyncio.to_thread(
                active_runtime.job_service.permission_policy.require,
                x_actor_id, "artifact.read", job.business_tags,
            )
        except PermissionDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        suffix = Path(job.original_name).suffix or Path(job.input_key).suffix or ".bin"
        cache_path = active_runtime.settings.local_data_dir / "original-preview" / job.job_id / f"original{suffix}"
        if not cache_path.is_file():
            try:
                await active_runtime.object_store.get_file(job.input_key, cache_path)
            except FileNotFoundError as exc:
                raise HTTPException(404, "原件不存在或已被清理") from exc
        media_type = mimetypes.guess_type(job.original_name)[0] or "application/octet-stream"
        return FileResponse(cache_path, media_type=media_type, filename=job.original_name)

    @app.get("/v1/jobs/{job_id}/standard-document/{asset_path:path}")
    async def get_standard_document_asset(
        job_id: str,
        asset_path: str,
        x_actor_id: str = Header(..., alias="X-Actor-ID"),
    ):
        """Read one file from the expanded standard-document package."""
        job = await active_runtime.repository.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "task or parsed result does not exist")
        try:
            await asyncio.to_thread(
                active_runtime.job_service.permission_policy.require,
                x_actor_id, "artifact.read", job.business_tags,
            )
        except PermissionDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        relative = PurePosixPath(asset_path)
        if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            raise HTTPException(400, "invalid standard-document asset path")
        package = job.result.get("standard_document") or {}
        object_prefix = package.get("object_prefix")
        if not object_prefix:
            raise HTTPException(404, "standard-document package is not available for this task")
        object_key = f"{object_prefix}/{relative.as_posix()}"
        cache_path = active_runtime.settings.local_data_dir / "standard-document-preview" / job_id
        for part in relative.parts:
            cache_path = cache_path / part
        if not cache_path.is_file():
            try:
                await active_runtime.object_store.get_file(object_key, cache_path)
            except FileNotFoundError as exc:
                raise HTTPException(404, "standard-document asset does not exist") from exc
        suffix_types = {
            ".md": "text/markdown; charset=utf-8",
            ".json": "application/json",
            ".jsonl": "application/x-ndjson",
            ".parquet": "application/vnd.apache.parquet",
            ".webp": "image/webp",
        }
        media_type = suffix_types.get(cache_path.suffix.lower()) or mimetypes.guess_type(cache_path.name)[0] or "application/octet-stream"
        return FileResponse(cache_path, media_type=media_type, filename=cache_path.name)

    @app.get("/v1/jobs/{job_id}/standard-document.zip")
    async def download_standard_document_package(
        job_id: str,
        x_actor_id: str = Header(..., alias="X-Actor-ID"),
    ):
        """Download the expanded object-store package as a portable ZIP file."""
        job = await active_runtime.repository.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "task or parsed result does not exist")
        try:
            await asyncio.to_thread(
                active_runtime.job_service.permission_policy.require,
                x_actor_id, "artifact.read", job.business_tags,
            )
        except PermissionDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        package = job.result.get("standard_document") or {}
        object_prefix = package.get("object_prefix")
        if not object_prefix:
            raise HTTPException(404, "standard-document package is not available for this task")
        cache_root = active_runtime.settings.local_data_dir / "standard-document-exports" / job_id / "v1"
        manifest_path = cache_root / "manifest.json"
        if not manifest_path.is_file():
            try:
                await active_runtime.object_store.get_file(f"{object_prefix}/manifest.json", manifest_path)
            except FileNotFoundError as exc:
                raise HTTPException(404, "standard-document manifest does not exist") from exc
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        relative_files = [PurePosixPath("manifest.json")]
        for name in manifest.get("artifacts", []):
            relative = PurePosixPath(str(name))
            if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                continue
            relative_files.append(relative)
        for relative in relative_files[1:]:
            local_path = cache_root.joinpath(*relative.parts)
            if not local_path.is_file():
                await active_runtime.object_store.get_file(f"{object_prefix}/{relative.as_posix()}", local_path)
        zip_path = cache_root.parent / f"standard-document-{job_id}-v1.zip"

        def create_zip() -> None:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for relative in relative_files:
                    archive.write(cache_root.joinpath(*relative.parts), arcname=f"standard-document/v1/{relative.as_posix()}")

        await asyncio.to_thread(create_zip)
        return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)

    @app.get("/v1/reviews")
    async def list_reviews(limit: int = 50, x_actor_id: str = Header(..., alias="X-Actor-ID")):
        jobs = await active_runtime.repository.pending_review_jobs(max(1, min(limit, 200)))
        items = []
        for job in jobs:
            try:
                await asyncio.to_thread(active_runtime.job_service.permission_policy.require, x_actor_id, "human.approve", job.business_tags)
            except PermissionDenied:
                continue
            decisions = await active_runtime.repository.reviews_for_job(job.job_id)
            items.append({
                "job_id": job.job_id,
                "original_name": job.original_name,
                "business_tags": job.business_tags,
                "pending_values": pending_values(job, decisions),
            })
        return {"items": items}

    @app.post("/v1/reviews/{job_id}/values/{value_id}")
    async def review_value(
        job_id: str,
        value_id: str,
        body: ReviewBody,
        x_actor_id: str = Header(..., alias="X-Actor-ID"),
    ):
        try:
            review = await active_runtime.job_service.review(
                job_id, value_id, x_actor_id, body.decision, body.corrected_value, body.note
            )
            job = await active_runtime.repository.get(job_id)
            return {"review": asdict(review), "job_status": job.status if job else None}
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc
        except PermissionDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    return app


app = create_app()
