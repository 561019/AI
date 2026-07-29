from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .jobs import InMemoryJobRepository, JobRepository, PostgresJobRepository
from .object_store import LocalObjectStore, ObjectStore, S3ObjectStore
from .parsers import OCRProvider
from .security import HttpPermissionPolicy, PermissionPolicy, StaticPermissionPolicy
from .service import AsyncDocumentWorker, DocumentJobService, TemplateCatalog
from .siliconflow_ocr import SiliconFlowPaddleOCRProvider


@dataclass
class Runtime:
    settings: Settings
    repository: JobRepository
    object_store: ObjectStore
    job_service: DocumentJobService
    worker: AsyncDocumentWorker
    templates: TemplateCatalog

    async def initialize(self) -> None:
        await self.repository.initialize()
        await self.object_store.initialize()

    async def close(self) -> None:
        await self.repository.close()
        close_ocr = getattr(self.worker.ocr_provider, "close", None)
        if close_ocr:
            close_ocr()


def build_runtime(settings: Settings | None = None, project_root: Path | None = None) -> Runtime:
    settings = settings or Settings.from_env()
    root = (project_root or Path.cwd()).resolve()
    data_dir = settings.local_data_dir.resolve()
    repository: JobRepository
    if settings.database_url:
        repository = PostgresJobRepository(settings.database_url)
    else:
        repository = InMemoryJobRepository()

    object_store: ObjectStore
    if settings.object_store_access_key and settings.object_store_secret_key:
        object_store = S3ObjectStore(
            settings.object_store_endpoint,
            settings.object_store_access_key,
            settings.object_store_secret_key,
            settings.object_store_bucket,
            settings.object_store_region,
        )
    else:
        object_store = LocalObjectStore(data_dir / "objects")

    ocr_provider: OCRProvider
    ocr_provider = SiliconFlowPaddleOCRProvider(
        api_key=settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url,
        model=settings.siliconflow_ocr_model,
        timeout_seconds=settings.ocr_timeout_seconds,
        max_retries=settings.ocr_max_retries,
        max_tokens=settings.ocr_max_tokens,
        default_confidence=settings.ocr_default_confidence,
        pdf_render_dpi=settings.pdf_render_dpi,
        pdf_max_pages=settings.pdf_max_pages,
        max_image_pixels=settings.ocr_max_image_pixels,
    )

    permission_policy: PermissionPolicy
    if settings.permission_api_url:
        permission_policy = HttpPermissionPolicy(settings.permission_api_url, settings.permission_api_key)
    else:
        permission_policy = StaticPermissionPolicy(allow_demo_actor=settings.allow_demo_actor)

    templates = TemplateCatalog(root / "templates")
    service = DocumentJobService(repository, object_store, templates, permission_policy)
    worker = AsyncDocumentWorker(repository, object_store, data_dir / "work", ocr_provider, permission_policy)
    return Runtime(settings, repository, object_store, service, worker, templates)
