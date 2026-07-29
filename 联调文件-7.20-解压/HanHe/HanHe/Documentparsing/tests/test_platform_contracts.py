from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from doc_table_engine.contracts import DocumentParseCommand
from doc_table_engine.jobs import InMemoryJobRepository
from doc_table_engine.object_store import LocalObjectStore
from doc_table_engine.security import StaticPermissionPolicy
from doc_table_engine.service import DocumentJobService, TemplateCatalog


def command() -> DocumentParseCommand:
    return DocumentParseCommand.model_validate({
        "message_id": "msg_parse_001", "trace_id": "trace_001", "request_id": "req_001",
        "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
        "target": {"layer": "L2", "service_code": "l2.document_table_parse"},
        "capability_dictionary_version": "2026.07.17", "registry_version": "registry_2026.07.17",
        "actor": {"person_id": "demo-user", "tenant_id": "tenant_demo"},
        "context": {"workflow_instance_id": "flow_001", "node_id": "node_001", "task_id": "task_001", "artifact_refs": [{
            "ref_id": "artifact_001", "storage_key": "artifacts/001/source.csv", "original_name": "source.csv",
            "data_labels": ["project:demo"], "allowed_actions": ["read"],
        }]},
        "idempotency_key": "flow_001-node_001-v1", "deadline_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    })


class PlatformContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatched_task_uses_artifact_ref_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = InMemoryJobRepository()
            store = LocalObjectStore(root / "objects")
            await repository.initialize()
            await store.initialize()
            service = DocumentJobService(repository, store, TemplateCatalog(root / "templates"), StaticPermissionPolicy(allow_demo_actor=True))
            first = await service.submit_dispatched(command())
            second = await service.submit_dispatched(command())
            self.assertEqual(first.job_id, second.job_id)
            self.assertEqual(first.input_key, "artifacts/001/source.csv")
            self.assertEqual(first.options["platform_envelope"]["trace_id"], "trace_001")

