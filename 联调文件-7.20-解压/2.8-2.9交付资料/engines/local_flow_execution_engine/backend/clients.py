from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class DependencyCallError(RuntimeError):
    def __init__(self, code: str, message: str, detail: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


def get_json(url: str, timeout: int = 10) -> dict[str, Any]:
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise DependencyCallError("dependency_unavailable", str(exc)) from exc


def post_json(url: str, payload: dict[str, Any], timeout: int = 90) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=body, method="POST", headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        raise DependencyCallError("dependency_failed", f"HTTP {exc.code}: {raw}", detail) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise DependencyCallError("dependency_unavailable", str(exc)) from exc
