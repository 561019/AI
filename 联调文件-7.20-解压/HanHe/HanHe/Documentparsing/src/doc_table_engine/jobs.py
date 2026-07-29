from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    REVIEW_REQUIRED = "review_required"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobRecord:
    job_id: str
    status: str
    actor_id: str
    business_tags: list[str]
    input_key: str
    original_name: str
    confidence_threshold: float = 0.85
    template_path: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    attempt_count: int = 0


@dataclass
class ReviewDecision:
    job_id: str
    value_id: str
    reviewer_id: str
    decision: str
    original_value: Any
    corrected_value: Any | None = None
    note: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class JobRepository(Protocol):
    async def initialize(self) -> None: ...
    async def close(self) -> None: ...
    async def create(self, job: JobRecord) -> None: ...
    async def find_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None: ...
    async def get(self, job_id: str) -> JobRecord | None: ...
    async def claim_next(self) -> JobRecord | None: ...
    async def complete(self, job_id: str, status: str, result: dict[str, Any]) -> None: ...
    async def register_package(self, job_id: str, package: dict[str, Any]) -> None: ...
    async def fail(self, job_id: str, error: str) -> None: ...
    async def save_review(self, decision: ReviewDecision) -> None: ...
    async def reviews_for_job(self, job_id: str) -> list[ReviewDecision]: ...
    async def pending_review_jobs(self, limit: int = 50) -> list[JobRecord]: ...


class InMemoryJobRepository:
    def __init__(self):
        self.jobs: dict[str, JobRecord] = {}
        self.reviews: dict[tuple[str, str], ReviewDecision] = {}
        self.packages: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def create(self, job: JobRecord) -> None:
        async with self._lock:
            if job.job_id in self.jobs:
                raise ValueError(f"任务已存在: {job.job_id}")
            self.jobs[job.job_id] = job

    async def get(self, job_id: str) -> JobRecord | None:
        return self.jobs.get(job_id)

    async def find_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
        return next((job for job in self.jobs.values() if job.options.get("platform_envelope", {}).get("idempotency_key") == idempotency_key), None)

    async def claim_next(self) -> JobRecord | None:
        async with self._lock:
            queued = sorted((job for job in self.jobs.values() if job.status == JobStatus.QUEUED), key=lambda item: item.created_at)
            if not queued:
                return None
            job = queued[0]
            job.status = JobStatus.RUNNING
            job.attempt_count += 1
            job.updated_at = datetime.now(UTC).isoformat()
            return job

    async def complete(self, job_id: str, status: str, result: dict[str, Any]) -> None:
        async with self._lock:
            job = self.jobs[job_id]
            job.status = status
            job.result = result
            job.error = None
            job.updated_at = datetime.now(UTC).isoformat()

    async def register_package(self, job_id: str, package: dict[str, Any]) -> None:
        async with self._lock:
            self.packages[job_id] = package

    async def fail(self, job_id: str, error: str) -> None:
        async with self._lock:
            job = self.jobs[job_id]
            job.status = JobStatus.FAILED
            job.error = error
            job.updated_at = datetime.now(UTC).isoformat()

    async def save_review(self, decision: ReviewDecision) -> None:
        async with self._lock:
            self.reviews[(decision.job_id, decision.value_id)] = decision
            job = self.jobs[decision.job_id]
            expected = int((job.result or {}).get("registration", {}).get("review_count", 0))
            completed = sum(1 for key in self.reviews if key[0] == decision.job_id)
            if expected and completed >= expected:
                job.status = JobStatus.COMPLETED
                job.updated_at = datetime.now(UTC).isoformat()

    async def reviews_for_job(self, job_id: str) -> list[ReviewDecision]:
        return [review for (stored_job_id, _), review in self.reviews.items() if stored_job_id == job_id]

    async def pending_review_jobs(self, limit: int = 50) -> list[JobRecord]:
        return [job for job in self.jobs.values() if job.status == JobStatus.REVIEW_REQUIRED][:limit]


class PostgresJobRepository:
    """基于 PostgreSQL `FOR UPDATE SKIP LOCKED` 的持久化任务队列。"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool = None

    async def initialize(self) -> None:
        try:
            import asyncpg
        except ImportError as exc:
            raise RuntimeError("PostgreSQL 支持需要安装: pip install -e .[api]") from exc
        self.pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=10)
        async with self.pool.acquire() as connection:
            await connection.execute(POSTGRES_SCHEMA)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    def _require_pool(self):
        if self.pool is None:
            raise RuntimeError("PostgresJobRepository 尚未 initialize")
        return self.pool

    async def create(self, job: JobRecord) -> None:
        pool = self._require_pool()
        await pool.execute(
            """INSERT INTO document_jobs
            (id,status,actor_id,business_tags,input_key,original_name,confidence_threshold,template_path,options,created_at,updated_at)
            VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8,$9::jsonb,$10::timestamptz,$11::timestamptz)""",
            job.job_id, job.status, job.actor_id, json.dumps(job.business_tags, ensure_ascii=False),
            job.input_key, job.original_name, job.confidence_threshold, job.template_path,
            json.dumps(job.options, ensure_ascii=False), self._as_datetime(job.created_at), self._as_datetime(job.updated_at),
        )

    async def get(self, job_id: str) -> JobRecord | None:
        row = await self._require_pool().fetchrow("SELECT * FROM document_jobs WHERE id=$1", job_id)
        return self._row(row) if row else None

    async def find_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
        row = await self._require_pool().fetchrow(
            "SELECT * FROM document_jobs WHERE options->'platform_envelope'->>'idempotency_key'=$1", idempotency_key,
        )
        return self._row(row) if row else None

    async def claim_next(self) -> JobRecord | None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """UPDATE document_jobs SET status='failed',
                    error='worker lease expired after maximum attempts',updated_at=now()
                    WHERE status='running' AND updated_at < now() - interval '15 minutes' AND attempt_count >= 3"""
                )
                row = await connection.fetchrow(
                    """WITH candidate AS (
                        SELECT id FROM document_jobs
                        WHERE (status='queued' OR (status='running' AND updated_at < now() - interval '15 minutes'))
                          AND attempt_count < 3
                        ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
                    )
                    UPDATE document_jobs j SET status='running', updated_at=now(), attempt_count=j.attempt_count+1
                    FROM candidate c WHERE j.id=c.id RETURNING j.*"""
                )
        return self._row(row) if row else None

    async def complete(self, job_id: str, status: str, result: dict[str, Any]) -> None:
        await self._require_pool().execute(
            "UPDATE document_jobs SET status=$2,result=$3::jsonb,error=NULL,updated_at=now() WHERE id=$1",
            job_id, status, json.dumps(result, ensure_ascii=False, default=str),
        )

    async def register_package(self, job_id: str, package: dict[str, Any]) -> None:
        await self._require_pool().execute(
            """INSERT INTO document_packages
            (job_id,document_id,package_version,profile,status,object_prefix,manifest_key,source_sha256,metadata,created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,now())
            ON CONFLICT (job_id) DO UPDATE SET
              package_version=excluded.package_version,profile=excluded.profile,status=excluded.status,
              object_prefix=excluded.object_prefix,manifest_key=excluded.manifest_key,
              source_sha256=excluded.source_sha256,metadata=excluded.metadata,created_at=now()""",
            job_id, package["document_id"], int(package["package_version"]), package["profile"],
            package["status"], package["object_prefix"], package["manifest_key"], package["source_sha256"],
            json.dumps(package, ensure_ascii=False, default=str),
        )

    async def fail(self, job_id: str, error: str) -> None:
        await self._require_pool().execute(
            "UPDATE document_jobs SET status='failed',error=$2,updated_at=now() WHERE id=$1", job_id, error[:4000]
        )

    async def save_review(self, decision: ReviewDecision) -> None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """INSERT INTO review_decisions
                    (job_id,value_id,reviewer_id,decision,original_value,corrected_value,note,created_at)
                    VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7,$8::timestamptz)
                    ON CONFLICT (job_id,value_id) DO UPDATE SET
                    reviewer_id=excluded.reviewer_id,decision=excluded.decision,
                    corrected_value=excluded.corrected_value,note=excluded.note,created_at=excluded.created_at""",
                    decision.job_id, decision.value_id, decision.reviewer_id, decision.decision,
                    json.dumps(decision.original_value, ensure_ascii=False, default=str),
                    json.dumps(decision.corrected_value, ensure_ascii=False, default=str),
                    decision.note, self._as_datetime(decision.created_at),
                )
                await connection.execute(
                    """UPDATE document_jobs j SET status='completed',updated_at=now()
                    WHERE j.id=$1
                      AND (j.result->'registration'->>'review_count')::int <=
                          (SELECT count(*) FROM review_decisions WHERE job_id=$1)""",
                    decision.job_id,
                )

    async def reviews_for_job(self, job_id: str) -> list[ReviewDecision]:
        rows = await self._require_pool().fetch("SELECT * FROM review_decisions WHERE job_id=$1 ORDER BY created_at", job_id)
        return [ReviewDecision(
            job_id=row["job_id"], value_id=row["value_id"], reviewer_id=row["reviewer_id"],
            decision=row["decision"], original_value=self._json(row["original_value"]),
            corrected_value=self._json(row["corrected_value"]), note=row["note"],
            created_at=row["created_at"].isoformat(),
        ) for row in rows]

    async def pending_review_jobs(self, limit: int = 50) -> list[JobRecord]:
        rows = await self._require_pool().fetch(
            "SELECT * FROM document_jobs WHERE status='review_required' ORDER BY updated_at LIMIT $1", limit
        )
        return [self._row(row) for row in rows]

    def _row(self, row) -> JobRecord:
        return JobRecord(
            job_id=row["id"], status=row["status"], actor_id=row["actor_id"],
            business_tags=list(self._json(row["business_tags"]) or []), input_key=row["input_key"],
            original_name=row["original_name"], confidence_threshold=float(row["confidence_threshold"]),
            template_path=row["template_path"], options=dict(self._json(row["options"]) or {}),
            result=self._json(row["result"]), error=row["error"],
            created_at=row["created_at"].isoformat(), updated_at=row["updated_at"].isoformat(),
            attempt_count=row["attempt_count"],
        )

    @staticmethod
    def _json(value):
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def _as_datetime(value: datetime | str) -> datetime:
        """Convert API-facing ISO timestamps into asyncpg-compatible values."""
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value.replace("Z", "+00:00"))


POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS document_jobs (
  id text PRIMARY KEY,
  status text NOT NULL CHECK (status IN ('queued','running','review_required','completed','failed')),
  actor_id text NOT NULL,
  business_tags jsonb NOT NULL,
  input_key text NOT NULL,
  original_name text NOT NULL,
  confidence_threshold double precision NOT NULL DEFAULT 0.85,
  template_path text,
  options jsonb NOT NULL DEFAULT '{}'::jsonb,
  result jsonb,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
  ,attempt_count integer NOT NULL DEFAULT 0
);
ALTER TABLE document_jobs ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS document_jobs_queue_idx ON document_jobs(status,created_at);
CREATE INDEX IF NOT EXISTS document_jobs_idempotency_idx ON document_jobs ((options->'platform_envelope'->>'idempotency_key'));
CREATE TABLE IF NOT EXISTS review_decisions (
  job_id text NOT NULL REFERENCES document_jobs(id) ON DELETE CASCADE,
  value_id text NOT NULL,
  reviewer_id text NOT NULL,
  decision text NOT NULL CHECK (decision IN ('confirm','correct','reject')),
  original_value jsonb,
  corrected_value jsonb,
  note text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(job_id,value_id)
);
CREATE TABLE IF NOT EXISTS document_packages (
  job_id text PRIMARY KEY REFERENCES document_jobs(id) ON DELETE CASCADE,
  document_id text NOT NULL,
  package_version integer NOT NULL,
  profile text NOT NULL,
  status text NOT NULL,
  object_prefix text NOT NULL,
  manifest_key text NOT NULL,
  source_sha256 text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS document_packages_document_idx ON document_packages(document_id,package_version);
"""
