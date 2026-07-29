from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from doc_table_engine.jobs import InMemoryJobRepository, JobStatus
from doc_table_engine.models import ParsedContent, ParsedValue, SourceRef
from doc_table_engine.object_store import LocalObjectStore
from doc_table_engine.security import StaticPermissionPolicy
from doc_table_engine.service import AsyncDocumentWorker, DocumentJobService, TemplateCatalog, pending_values


class StubOCRProvider:
    def recognize(self, path: Path, file_hash: str) -> ParsedContent:
        return ParsedContent(text_blocks=[ParsedValue(
            raw_value="金额：1280.50",
            confidence=0.55,
            source=SourceRef(file_hash, path.name, page=1, bbox=(1, 2, 3, 4)),
        )])


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repository = InMemoryJobRepository()
        self.object_store = LocalObjectStore(self.root / "objects")
        self.policy = StaticPermissionPolicy(allow_demo_actor=True)
        self.service = DocumentJobService(
            self.repository,
            self.object_store,
            TemplateCatalog(self.root / "templates"),
            self.policy,
        )
        self.worker = AsyncDocumentWorker(
            self.repository,
            self.object_store,
            self.root / "work",
            StubOCRProvider(),
            self.policy,
        )
        await self.repository.initialize()
        await self.object_store.initialize()

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.temp.cleanup()

    async def test_async_job_and_review_lifecycle(self) -> None:
        source = self.root / "scan.png"
        source.write_bytes(b"image-placeholder")
        job = await self.service.submit(
            source, source.name, "demo-user", ["experiment:demo"], confidence_threshold=0.85
        )
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertTrue(await self.worker.run_once())

        stored = await self.repository.get(job.job_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, JobStatus.REVIEW_REQUIRED)
        decisions = await self.repository.reviews_for_job(job.job_id)
        values = pending_values(stored, decisions)
        self.assertEqual(len(values), 1)
        self.assertFalse(values[0]["auto_fill_allowed"])

        await self.service.review(
            job.job_id, values[0]["value_id"], "demo-user", "correct", "1280.50", "人工核对原件"
        )
        stored = await self.repository.get(job.job_id)
        self.assertEqual(stored.status, JobStatus.COMPLETED)
        self.assertEqual(len(await self.repository.reviews_for_job(job.job_id)), 1)

    async def test_structured_job_completes_without_review(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("区域,销售额\n华东,125000.00\n", encoding="utf-8")
        job = await self.service.submit(source, source.name, "demo-user", ["project:demo"])
        await self.worker.run_once()
        stored = await self.repository.get(job.job_id)
        self.assertEqual(stored.status, JobStatus.COMPLETED)
        self.assertEqual(stored.result["registration"]["job_id"], job.job_id)
        package = stored.result["standard_document"]
        self.assertEqual(package["schema"], "standard-document/v1")
        self.assertTrue((self.root / "objects" / package["manifest_key"]).is_file())
        self.assertTrue((self.root / "objects" / package["blocks_key"]).is_file())
