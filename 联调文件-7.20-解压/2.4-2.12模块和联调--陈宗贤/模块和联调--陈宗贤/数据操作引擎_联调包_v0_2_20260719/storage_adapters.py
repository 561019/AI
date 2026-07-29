from __future__ import annotations

import hashlib
import json
import sqlite3
import base64
import binascii
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_ref(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


class SQLiteDataModuleAdapter:
    """Local L1.7 adapter.

    It deliberately owns physical object writes, version reads and logical
    deletes.  The L2 data-operation engine must not write object files or the
    L1.7 warehouse ledger itself.  Production can replace this adapter with
    object storage / a database without changing the L2 business-asset ledger.
    """

    def __init__(self, conn: sqlite3.Connection, dataset_dir: Path) -> None:
        self.conn = conn
        self.dataset_dir = dataset_dir
        self.object_dir = dataset_dir.parent / "business_objects"
        self.file_dir = self.object_dir / "files"
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self.object_dir.mkdir(parents=True, exist_ok=True)
        self.file_dir.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                dataset_ref TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL UNIQUE,
                request_id TEXT NOT NULL,
                owner_actor_id TEXT NOT NULL,
                dataset_name TEXT NOT NULL,
                metric_id TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                storage_format TEXT NOT NULL,
                storage_uri TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                result_hash TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_datasets_owner_created
                ON datasets(owner_actor_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS l1_data_object_versions (
                data_ref TEXT NOT NULL,
                version INTEGER NOT NULL,
                storage_uri TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                physical_state TEXT NOT NULL,
                stored_at TEXT NOT NULL,
                PRIMARY KEY(data_ref, version)
            );
            CREATE INDEX IF NOT EXISTS idx_l1_object_versions_ref
                ON l1_data_object_versions(data_ref, version DESC);
            """
        )
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(l1_data_object_versions)")}
        if "artifact_json" not in columns:
            self.conn.execute("ALTER TABLE l1_data_object_versions ADD COLUMN artifact_json TEXT NOT NULL DEFAULT '{}'")

    def store_business_object(
        self,
        *,
        data_ref: str,
        version: int,
        content: dict[str, Any],
        artifact: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one L1.7 business object and update its current warehouse pointer."""
        if not data_ref or int(version) < 1 or not isinstance(content, dict):
            raise ValueError("invalid_business_object")
        content_hash = hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()
        artifact_metadata = self._store_binary_artifact(data_ref=data_ref, version=int(version), artifact=artifact)
        filename = f"{data_ref}-v{int(version)}.json"
        path = self.object_dir / filename
        temporary = self.object_dir / f"{filename}.tmp"
        artifact = {
            "data_ref": data_ref,
            "version": int(version),
            "storage_format": "json",
            "content": content,
            "content_hash": content_hash,
            "artifact": artifact_metadata,
            "stored_at": _now_iso(),
        }
        storage_uri = f"l1mock://data-module/business-objects/{filename}"
        stored_at = artifact["stored_at"]
        try:
            temporary.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
            self.conn.execute(
                """INSERT OR REPLACE INTO l1_data_object_versions
                   (data_ref, version, storage_uri, content_hash, physical_state, stored_at, artifact_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (data_ref, int(version), storage_uri, content_hash, "stored", stored_at, _canonical_json(artifact_metadata)),
            )
            self.conn.execute(
                """INSERT OR REPLACE INTO l1_data_locations
                   (data_ref, storage_uri, content_hash, physical_state, stored_at)
                   VALUES (?,?,?,?,?)""",
                (data_ref, storage_uri, content_hash, "stored", stored_at),
            )
        except Exception:
            temporary.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            self._delete_binary_artifact(artifact_metadata)
            raise
        return {
            "storage_uri": storage_uri,
            "content_hash": content_hash,
            "physical_state": "stored",
            "stored_at": stored_at,
            "version": int(version),
            "artifact": artifact_metadata,
        }

    def read_business_object(self, *, data_ref: str, version: int | None = None, include_artifact_content: bool = False) -> dict[str, Any]:
        """Read a stored JSON object through the L1.7 seam, never from L2."""
        if version is None:
            row = self.conn.execute(
                "SELECT * FROM l1_data_locations WHERE data_ref=?", (data_ref,)
            ).fetchone()
            if row is None:
                raise KeyError("business_object_not_found")
            version_row = self.conn.execute(
                "SELECT * FROM l1_data_object_versions WHERE data_ref=? AND storage_uri=?",
                (data_ref, row["storage_uri"]),
            ).fetchone()
        else:
            version_row = self.conn.execute(
                "SELECT * FROM l1_data_object_versions WHERE data_ref=? AND version=?",
                (data_ref, int(version)),
            ).fetchone()
        if version_row is None:
            raise KeyError("business_object_version_not_found")
        if version_row["physical_state"] != "stored":
            raise PermissionError("business_object_deleted")
        filename = Path(str(version_row["storage_uri"])).name
        path = self.object_dir / filename
        if not path.is_file() or path.parent.resolve() != self.object_dir.resolve():
            raise FileNotFoundError("business_object_artifact_missing")
        stored_object = json.loads(path.read_text(encoding="utf-8"))
        artifact_metadata = stored_object.get("artifact") if isinstance(stored_object.get("artifact"), dict) else json.loads(version_row["artifact_json"] or "{}")
        if include_artifact_content and artifact_metadata:
            artifact_metadata = {**artifact_metadata, "content_base64": self._read_binary_artifact(artifact_metadata)}
        return {
            "data_ref": data_ref,
            "version": int(stored_object["version"]),
            "storage_uri": version_row["storage_uri"],
            "content_hash": version_row["content_hash"],
            "content": stored_object["content"],
            "artifact": artifact_metadata if isinstance(artifact_metadata, dict) else {},
        }

    def _store_binary_artifact(self, *, data_ref: str, version: int, artifact: dict[str, Any] | None) -> dict[str, Any]:
        """Keep binary decoding, paths and hashes behind the L1.7 adapter seam."""
        if artifact is None:
            return {}
        if not isinstance(artifact, dict):
            raise ValueError("artifact_must_be_object")
        filename = str(artifact.get("filename") or "").strip()
        media_type = str(artifact.get("media_type") or "application/octet-stream").strip()
        encoded = artifact.get("content_base64")
        if not filename or not isinstance(encoded, str) or not encoded:
            raise ValueError("artifact_filename_and_content_base64_required")
        try:
            binary = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("artifact_content_base64_invalid") from exc
        if not binary:
            raise ValueError("artifact_content_empty")
        if len(binary) > 10 * 1024 * 1024:
            raise ValueError("artifact_too_large")
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename).strip("._") or "artifact.bin"
        stored_filename = f"{data_ref}-v{version}-{safe_name}"
        path = self.file_dir / stored_filename
        temporary = self.file_dir / f"{stored_filename}.tmp"
        temporary.write_bytes(binary)
        temporary.replace(path)
        content_hash = hashlib.sha256(binary).hexdigest()
        return {
            "artifact_ref": _stable_ref("artifact", f"{data_ref}:{version}:{content_hash}"),
            "filename": filename,
            "media_type": media_type,
            "size_bytes": len(binary),
            "content_hash": content_hash,
            "storage_uri": f"l1mock://data-module/business-objects/files/{stored_filename}",
        }

    def _read_binary_artifact(self, artifact: dict[str, Any]) -> str:
        filename = Path(str(artifact.get("storage_uri") or "")).name
        path = self.file_dir / filename
        if not filename or not path.is_file() or path.parent.resolve() != self.file_dir.resolve():
            raise FileNotFoundError("binary_artifact_missing")
        binary = path.read_bytes()
        if hashlib.sha256(binary).hexdigest() != artifact.get("content_hash"):
            raise ValueError("binary_artifact_hash_mismatch")
        return base64.b64encode(binary).decode("ascii")

    def _delete_binary_artifact(self, artifact: dict[str, Any]) -> None:
        """Best-effort rollback for a failed metadata write after a binary file was created."""
        storage_uri = str(artifact.get("storage_uri") or "")
        filename = Path(storage_uri).name
        path = self.file_dir / filename
        if filename and path.parent.resolve() == self.file_dir.resolve():
            path.unlink(missing_ok=True)

    def mark_business_object_deleted(self, *, data_ref: str) -> dict[str, Any]:
        """Logical deletion keeps historical evidence; physical purge needs a retention job."""
        row = self.conn.execute(
            "SELECT * FROM l1_data_locations WHERE data_ref=?", (data_ref,)
        ).fetchone()
        if row is None:
            raise KeyError("business_object_not_found")
        deleted_at = _now_iso()
        self.conn.execute(
            "UPDATE l1_data_locations SET physical_state=?, stored_at=? WHERE data_ref=?",
            ("deleted", deleted_at, data_ref),
        )
        self.conn.execute(
            """UPDATE l1_data_object_versions SET physical_state=?
               WHERE data_ref=? AND storage_uri=?""",
            ("deleted", data_ref, row["storage_uri"]),
        )
        return {"storage_uri": row["storage_uri"], "content_hash": row["content_hash"], "physical_state": "deleted", "deleted_at": deleted_at}

    def store_dataset(
        self,
        *,
        trace_id: str,
        request_id: str,
        actor_id: str,
        dataset_name: str,
        metric: dict[str, Any],
        dimensions: list[str],
        rows: list[dict[str, Any]],
        source_refs: list[str],
        verification: dict[str, Any],
        result_hash: str,
    ) -> dict[str, Any]:
        existing = self.conn.execute(
            "SELECT * FROM datasets WHERE trace_id=?", (trace_id,)
        ).fetchone()
        if existing is not None:
            return self._public(existing)

        dataset_ref = _stable_ref("dataset", trace_id)
        artifact = {
            "schema_version": "1.0",
            "dataset_ref": dataset_ref,
            "task_ref": trace_id,
            "owner_actor_id": actor_id,
            "dataset_name": dataset_name,
            "schema": [
                *[{"field": name, "data_type": "string"} for name in dimensions],
                {"field": "value", "data_type": "decimal", "unit": metric["unit"], "scale": metric["scale"]},
                {"field": "source_count", "data_type": "integer"},
            ],
            "rows": rows,
            "lineage": {
                "source_refs": sorted(set(source_refs)),
                "source_record_count": len(set(source_refs)),
                "aggregation_rule_version": "deterministic-sum-v1",
            },
            "quality": {"status": "passed", **verification},
            "result_hash": result_hash,
            "created_at": _now_iso(),
        }
        filename = f"{dataset_ref}.json"
        path = self.dataset_dir / filename
        temporary = self.dataset_dir / f"{filename}.tmp"
        temporary.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

        metadata = {
            "lineage_source_count": len(set(source_refs)),
            "aggregation_rule_version": "deterministic-sum-v1",
            "calculation_owner": "固定确定性程序（非大模型）",
        }
        self.conn.execute(
            """INSERT INTO datasets
               (dataset_ref, trace_id, request_id, owner_actor_id, dataset_name,
                metric_id, schema_version, storage_format, storage_uri, row_count,
                result_hash, quality_status, metadata_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                dataset_ref,
                trace_id,
                request_id,
                actor_id,
                dataset_name,
                metric["metric_id"],
                "1.0",
                "json",
                f"datasets/{filename}",
                len(rows),
                result_hash,
                "passed",
                _canonical_json(metadata),
                artifact["created_at"],
            ),
        )
        row = self.conn.execute(
            "SELECT * FROM datasets WHERE dataset_ref=?", (dataset_ref,)
        ).fetchone()
        return self._public(row)

    def list_datasets(self, actor_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM datasets WHERE owner_actor_id=? ORDER BY created_at DESC LIMIT ?",
            (actor_id, min(max(int(limit), 1), 100)),
        ).fetchall()
        return [self._public(row) for row in rows]

    def get_dataset(self, dataset_ref: str, actor_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM datasets WHERE dataset_ref=?", (dataset_ref,)
        ).fetchone()
        if row is None:
            raise KeyError("dataset_not_found")
        if row["owner_actor_id"] != actor_id:
            raise PermissionError("dataset_not_visible")
        path = self.dataset_dir.parent / row["storage_uri"]
        if not path.is_file() or path.parent.resolve() != self.dataset_dir.resolve():
            raise FileNotFoundError("dataset_artifact_missing")
        return {"metadata": self._public(row), "artifact": json.loads(path.read_text(encoding="utf-8"))}

    def get_by_trace(self, trace_id: str, actor_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM datasets WHERE trace_id=?", (trace_id,)
        ).fetchone()
        if row is None:
            return None
        if row["owner_actor_id"] != actor_id:
            raise PermissionError("dataset_not_visible")
        return self._public(row)

    def clear_artifacts(self) -> None:
        for path in self.dataset_dir.glob("dataset-*.json"):
            if path.is_file() and path.parent.resolve() == self.dataset_dir.resolve():
                path.unlink()
        for path in self.dataset_dir.glob("dataset-*.json.tmp"):
            if path.is_file() and path.parent.resolve() == self.dataset_dir.resolve():
                path.unlink()

    def clear_business_objects(self) -> None:
        """Reset only local mock objects owned by this adapter."""
        for path in self.object_dir.glob("data-*-v*.json"):
            if path.is_file() and path.parent.resolve() == self.object_dir.resolve():
                path.unlink()
        for path in self.object_dir.glob("data-*-v*.json.tmp"):
            if path.is_file() and path.parent.resolve() == self.object_dir.resolve():
                path.unlink()
        for path in self.file_dir.iterdir():
            if path.is_file() and path.parent.resolve() == self.file_dir.resolve():
                path.unlink()
        self.conn.execute("DELETE FROM l1_data_object_versions")

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "dataset_ref": row["dataset_ref"],
            "trace_id": row["trace_id"],
            "request_id": row["request_id"],
            "owner_actor_id": row["owner_actor_id"],
            "dataset_name": row["dataset_name"],
            "metric_id": row["metric_id"],
            "schema_version": row["schema_version"],
            "storage_format": row["storage_format"],
            "storage_uri": row["storage_uri"],
            "row_count": row["row_count"],
            "result_hash": row["result_hash"],
            "quality_status": row["quality_status"],
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
        }


class SQLiteMemoryManagementAdapter:
    """Local L1.15 adapter that stores preferences, never business values."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_candidates (
                candidate_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL UNIQUE,
                actor_id TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                content_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                decided_at TEXT
            );
            CREATE TABLE IF NOT EXISTS memories (
                memory_ref TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL UNIQUE,
                actor_id TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                content_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memory_candidates_actor_created
                ON memory_candidates(actor_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memories_actor_created
                ON memories(actor_id, created_at DESC);
            """
        )

    def create_candidate(
        self,
        *,
        trace_id: str,
        actor_id: str,
        content: dict[str, Any],
        dataset_ref: str,
        result_hash: str,
    ) -> dict[str, Any]:
        existing = self.conn.execute(
            "SELECT * FROM memory_candidates WHERE trace_id=?", (trace_id,)
        ).fetchone()
        if existing is not None:
            return self._candidate_public(existing)
        candidate_id = _stable_ref("memory-candidate", trace_id)
        evidence = {
            "trace_id": trace_id,
            "dataset_ref": dataset_ref,
            "result_hash": result_hash,
        }
        created_at = _now_iso()
        self.conn.execute(
            """INSERT INTO memory_candidates
               (candidate_id, trace_id, actor_id, memory_type, content_json,
                evidence_json, status, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                candidate_id,
                trace_id,
                actor_id,
                "aggregation_preference",
                _canonical_json(content),
                _canonical_json(evidence),
                "pending",
                created_at,
            ),
        )
        row = self.conn.execute(
            "SELECT * FROM memory_candidates WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        return self._candidate_public(row)

    def decide(self, candidate_id: str, actor_id: str, decision: str) -> dict[str, Any]:
        normalized = {"confirm": "confirmed", "confirmed": "confirmed", "reject": "rejected", "rejected": "rejected"}.get(decision)
        if normalized is None:
            raise ValueError("memory_decision_invalid")
        row = self.conn.execute(
            "SELECT * FROM memory_candidates WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise KeyError("memory_candidate_not_found")
        if row["actor_id"] != actor_id:
            raise PermissionError("memory_candidate_not_visible")
        if row["status"] != "pending":
            if row["status"] == normalized:
                return self._decision_result(row)
            raise ValueError("memory_candidate_already_decided")

        decided_at = _now_iso()
        self.conn.execute(
            "UPDATE memory_candidates SET status=?, decided_at=? WHERE candidate_id=?",
            (normalized, decided_at, candidate_id),
        )
        if normalized == "confirmed":
            memory_ref = _stable_ref("memory", candidate_id)
            self.conn.execute(
                """INSERT OR IGNORE INTO memories
                   (memory_ref, candidate_id, actor_id, memory_type, content_json,
                    evidence_json, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    memory_ref,
                    candidate_id,
                    actor_id,
                    row["memory_type"],
                    row["content_json"],
                    row["evidence_json"],
                    "active",
                    decided_at,
                ),
            )
        updated = self.conn.execute(
            "SELECT * FROM memory_candidates WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        return self._decision_result(updated)

    def list_candidates(self, actor_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM memory_candidates WHERE actor_id=? ORDER BY created_at DESC LIMIT ?",
            (actor_id, min(max(int(limit), 1), 100)),
        ).fetchall()
        return [self._candidate_public(row) for row in rows]

    def list_memories(self, actor_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE actor_id=? ORDER BY created_at DESC LIMIT ?",
            (actor_id, min(max(int(limit), 1), 100)),
        ).fetchall()
        return [self._memory_public(row) for row in rows]

    def get_candidate_by_trace(self, trace_id: str, actor_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM memory_candidates WHERE trace_id=?", (trace_id,)
        ).fetchone()
        if row is None:
            return None
        if row["actor_id"] != actor_id:
            raise PermissionError("memory_candidate_not_visible")
        return self._candidate_public(row)

    def _decision_result(self, candidate: sqlite3.Row) -> dict[str, Any]:
        result = {"candidate": self._candidate_public(candidate), "memory": None}
        memory = self.conn.execute(
            "SELECT * FROM memories WHERE candidate_id=?", (candidate["candidate_id"],)
        ).fetchone()
        if memory is not None:
            result["memory"] = self._memory_public(memory)
        return result

    @staticmethod
    def _candidate_public(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "candidate_id": row["candidate_id"],
            "trace_id": row["trace_id"],
            "actor_id": row["actor_id"],
            "memory_type": row["memory_type"],
            "content": json.loads(row["content_json"]),
            "evidence": json.loads(row["evidence_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "decided_at": row["decided_at"],
        }

    @staticmethod
    def _memory_public(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "memory_ref": row["memory_ref"],
            "candidate_id": row["candidate_id"],
            "actor_id": row["actor_id"],
            "memory_type": row["memory_type"],
            "content": json.loads(row["content_json"]),
            "evidence": json.loads(row["evidence_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
        }
