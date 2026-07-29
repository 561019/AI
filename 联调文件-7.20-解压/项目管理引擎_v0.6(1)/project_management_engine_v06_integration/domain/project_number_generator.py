from __future__ import annotations

from datetime import datetime


def generate_project_number(repository, now: datetime | None = None) -> str:
    now = now or datetime.now()
    date_key = now.strftime("%Y%m%d")
    sequence = repository.next_project_sequence(date_key)
    return f"PRJ-{date_key}-{sequence:04d}"
