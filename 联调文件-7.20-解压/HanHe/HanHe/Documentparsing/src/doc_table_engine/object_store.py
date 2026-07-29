from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Protocol


class ObjectStore(Protocol):
    async def initialize(self) -> None: ...
    async def put_file(self, source: Path, key: str) -> None: ...
    async def get_file(self, key: str, destination: Path) -> None: ...


class LocalObjectStore:
    def __init__(self, root: Path):
        self.root = root

    async def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    async def put_file(self, source: Path, key: str) -> None:
        destination = self._safe_path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, source, destination)

    async def get_file(self, key: str, destination: Path) -> None:
        source = self._safe_path(key)
        if not source.is_file():
            raise FileNotFoundError(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, source, destination)

    def _safe_path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        root = self.root.resolve()
        if root != path and root not in path.parents:
            raise ValueError("非法对象键")
        return path


class S3ObjectStore:
    """兼容 AWS S3、MinIO 及其他 S3 API 对象存储。"""

    def __init__(self, endpoint: str | None, access_key: str, secret_key: str, bucket: str, region: str):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("S3 支持需要安装: pip install -e .[api]") from exc
        self.bucket = bucket
        self.client = boto3.client(
            "s3", endpoint_url=endpoint, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, region_name=region,
        )

    async def initialize(self) -> None:
        def ensure_bucket():
            try:
                self.client.head_bucket(Bucket=self.bucket)
            except Exception:
                self.client.create_bucket(Bucket=self.bucket)
        await asyncio.to_thread(ensure_bucket)

    async def put_file(self, source: Path, key: str) -> None:
        await asyncio.to_thread(self.client.upload_file, str(source), self.bucket, key)

    async def get_file(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self.client.download_file, self.bucket, key, str(destination))
