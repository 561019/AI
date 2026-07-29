from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    object_store_endpoint: str | None
    object_store_access_key: str | None
    object_store_secret_key: str | None
    object_store_bucket: str
    object_store_region: str
    local_data_dir: Path
    ocr_timeout_seconds: float
    ocr_max_retries: int
    ocr_max_tokens: int
    ocr_default_confidence: float
    pdf_render_dpi: int
    pdf_max_pages: int
    ocr_max_image_pixels: int
    siliconflow_base_url: str
    siliconflow_api_key: str | None
    siliconflow_ocr_model: str
    enable_embedded_worker: bool
    worker_poll_seconds: float
    allow_demo_actor: bool
    permission_api_url: str | None
    permission_api_key: str | None
    max_upload_bytes: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL"),
            object_store_endpoint=os.getenv("OBJECT_STORE_ENDPOINT"),
            object_store_access_key=os.getenv("OBJECT_STORE_ACCESS_KEY"),
            object_store_secret_key=os.getenv("OBJECT_STORE_SECRET_KEY"),
            object_store_bucket=os.getenv("OBJECT_STORE_BUCKET", "document-engine"),
            object_store_region=os.getenv("OBJECT_STORE_REGION", "us-east-1"),
            local_data_dir=Path(os.getenv("LOCAL_DATA_DIR", "service-data")),
            ocr_timeout_seconds=float(os.getenv("OCR_TIMEOUT_SECONDS", "180")),
            ocr_max_retries=int(os.getenv("OCR_MAX_RETRIES", "3")),
            ocr_max_tokens=int(os.getenv("OCR_MAX_TOKENS", "8192")),
            ocr_default_confidence=float(os.getenv("OCR_DEFAULT_CONFIDENCE", "0.80")),
            pdf_render_dpi=int(os.getenv("PDF_RENDER_DPI", "144")),
            pdf_max_pages=int(os.getenv("PDF_MAX_PAGES", "100")),
            ocr_max_image_pixels=int(os.getenv("OCR_MAX_IMAGE_PIXELS", "4000000")),
            siliconflow_base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
            siliconflow_api_key=os.getenv("SILICONFLOW_API_KEY"),
            siliconflow_ocr_model=os.getenv("SILICONFLOW_OCR_MODEL", "PaddlePaddle/PaddleOCR-VL-1.5"),
            enable_embedded_worker=_bool("ENABLE_EMBEDDED_WORKER", True),
            worker_poll_seconds=float(os.getenv("WORKER_POLL_SECONDS", "1.0")),
            allow_demo_actor=_bool("ALLOW_DEMO_ACTOR", False),
            permission_api_url=os.getenv("PERMISSION_API_URL"),
            permission_api_key=os.getenv("PERMISSION_API_KEY"),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024))),
        )
