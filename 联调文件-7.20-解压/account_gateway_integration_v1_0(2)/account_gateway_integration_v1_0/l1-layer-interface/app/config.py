from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8002
    service_secret: str = ""
    permission_url: str = "http://127.0.0.1:8001"
    permission_mechanism_secret: str = ""
    target_service_secret: str = ""
    identity_context_secret: str = ""
    account_gateway_url: str = "http://127.0.0.1:8080"
    timeout_ms: int = 2000

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("L1_INTERFACE_HOST", "127.0.0.1"),
            port=int(os.getenv("L1_INTERFACE_PORT", "8002")),
            service_secret=os.getenv("L1_INTERFACE_SERVICE_SECRET", ""),
            permission_url=os.getenv("L1_INTERFACE_PERMISSION_URL", "http://127.0.0.1:8001").rstrip("/"),
            permission_mechanism_secret=os.getenv("L1_INTERFACE_PERMISSION_MECHANISM_SECRET", ""),
            target_service_secret=os.getenv("L1_INTERFACE_TARGET_SERVICE_SECRET", ""),
            identity_context_secret=os.getenv("L1_INTERFACE_IDENTITY_CONTEXT_SECRET", ""),
            account_gateway_url=os.getenv("L1_INTERFACE_ACCOUNT_GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/"),
            timeout_ms=int(os.getenv("L1_INTERFACE_TIMEOUT_MS", "2000")),
        )
