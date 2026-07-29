from __future__ import annotations

import json
import shutil
from pathlib import Path

from .models import ParseResult


class LocalThreeSplitStore:
    """MVP 三拆存储；生产环境分别接对象存储、关系库、向量/语义库。"""

    def __init__(self, root: Path):
        self.root = root

    def save(self, source: Path, result: ParseResult) -> ParseResult:
        originals = self.root / "originals"
        registrations = self.root / "registrations"
        semantics = self.root / "semantics"
        for folder in (originals, registrations, semantics):
            folder.mkdir(parents=True, exist_ok=True)
        destination = originals / f"{result.original.sha256}{source.suffix.lower()}"
        if not destination.exists():
            shutil.copy2(source, destination)
        result.original.stored_path = str(destination.resolve())
        self._write_json(registrations / f"{result.registration.job_id}.json", {
            "original": result.to_dict()["original"],
            "registration": result.to_dict()["registration"],
        })
        self._write_json(semantics / f"{result.registration.job_id}.json", {
            "job_id": result.registration.job_id,
            "business_tags": result.registration.business_tags,
            "semantic": result.to_dict()["semantic"],
        })
        return result

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

