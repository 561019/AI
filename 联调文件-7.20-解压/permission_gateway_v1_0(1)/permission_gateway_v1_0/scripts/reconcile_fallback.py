from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.database import Database
from app.models import PermissionDecision


def main() -> None:
    parser = argparse.ArgumentParser(description="Import fallback permission audit events")
    parser.add_argument("path", type=Path, nargs="?", default=Path("logs/permission-fallback.ndjson"))
    args = parser.parse_args()
    if not args.path.is_file():
        raise SystemExit(f"fallback log not found: {args.path}")
    database = Database(Settings.from_env())
    database.initialize_schema()
    imported = 0
    with database.session() as session:
        for line in args.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            now = datetime.now(timezone.utc)
            session.add(
                PermissionDecision(
                    decision_id=None,
                    trace_id=str(payload.get("trace_id", "")),
                    request_id=str(payload.get("request_id", "")),
                    actor_id=str(payload.get("actor_id", "")),
                    person_id=payload.get("person_id"),
                    position_id=payload.get("position_id"),
                    tenant_id=payload.get("tenant_id"),
                    action=str(payload.get("action", "")),
                    source_service=str(payload.get("source_service", "")),
                    target_service=str(payload.get("target_service", "")),
                    resource_type=payload.get("resource_type"),
                    resource_id=payload.get("resource_id"),
                    data_label=str(payload.get("data_label", "")),
                    data_state=str(payload.get("data_state", "")),
                    allowed=False,
                    result="error",
                    reason_code=str(payload.get("reason_code", "PERMISSION_SERVICE_ERROR")),
                    reason=str(payload.get("reason", "fallback audit")),
                    policy_id=None,
                    four_factors_json=None,
                    error_json=json.dumps(payload.get("details", {}), ensure_ascii=False),
                    requested_at=now,
                    decided_at=now,
                )
            )
            imported += 1
        session.commit()
    print(f"imported {imported} fallback audit events")


if __name__ == "__main__":
    main()
