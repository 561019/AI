from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _module_root() -> Path:
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8001
    database_url: str = "sqlite:///./data/permission.sqlite3"
    log_level: str = "INFO"
    logs_dir: Path = _module_root() / "logs"
    timezone: str = "Asia/Hong_Kong"
    # The layer interface uses this only to authenticate the mechanism-direct path.
    # In production it is replaced by the mTLS client identity check.
    mechanism_secret: str = ""
    version: str = "1.0.0"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("PERMISSION_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=int(os.getenv("PERMISSION_PORT", "8001")),
            database_url=os.getenv(
                "PERMISSION_DATABASE_URL", "sqlite:///./data/permission.sqlite3"
            ).strip(),
            log_level=os.getenv("PERMISSION_LOG_LEVEL", "INFO").strip().upper(),
            logs_dir=Path(
                os.getenv("PERMISSION_LOG_DIR", str(_module_root() / "logs"))
            ).resolve(),
            timezone=os.getenv("PERMISSION_TIMEZONE", "Asia/Hong_Kong").strip(),
            mechanism_secret=os.getenv("PERMISSION_MECHANISM_SECRET", "").strip(),
        )
