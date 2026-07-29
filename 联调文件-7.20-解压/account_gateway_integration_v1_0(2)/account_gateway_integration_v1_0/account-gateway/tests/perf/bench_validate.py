import base64
import hashlib
import hmac
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests


BASE_URL = os.environ.get("ACCOUNT_GATEWAY_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
THREADS = 10
REQUESTS_PER_THREAD = 100
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("PERF_REQUEST_TIMEOUT", "2"))


def main() -> None:
    token = sign_jwt(
        {"user_id": "perf-user", "org_id": "perf-org", "role_list": ["staff"]},
        secret=os.environ.get("JWT_SECRET", "change-me"),
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Request-ID": "perf-validate",
        "X-Client-ID": "perf",
        "X-User-ID": "tool_owner_placeholder",
        "X-Resource-Type": "tool",
        "X-Resource-Owner-ID": "tool_owner_placeholder",
        "X-Action": "create",
    }

    wait_for_gateway()
    latencies_ms = run_benchmark(headers)
    p50 = percentile(latencies_ms, 50)
    p95 = percentile(latencies_ms, 95)
    p99 = percentile(latencies_ms, 99)

    print(f"requests={len(latencies_ms)} threads={THREADS} per_thread={REQUESTS_PER_THREAD}")
    print(f"p50={p50:.2f}ms")
    print(f"p95={p95:.2f}ms")
    print(f"p99={p99:.2f}ms")


def wait_for_gateway() -> None:
    health_url = f"{BASE_URL}/health"
    deadline = time.monotonic() + 10
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            response = requests.get(health_url, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 200:
                return
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(0.2)

    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"gateway did not become healthy at {health_url}{detail}")


def run_benchmark(headers: dict[str, str]) -> list[float]:
    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(run_worker, headers) for _ in range(THREADS)]
        latencies_ms: list[float] = []
        for future in as_completed(futures):
            latencies_ms.extend(future.result())
    return latencies_ms


def run_worker(headers: dict[str, str]) -> list[float]:
    session = requests.Session()
    latencies_ms: list[float] = []

    for _ in range(REQUESTS_PER_THREAD):
        started = time.perf_counter()
        response = session.post(
            f"{BASE_URL}/auth/validate",
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.raise_for_status()

        body = response.json()
        if body.get("allow") is not True:
            raise AssertionError(f"unexpected validate response: {body}")

        latencies_ms.append(elapsed_ms)

    return latencies_ms


def percentile(values: list[float], percentile_value: int) -> float:
    if not values:
        raise ValueError("cannot calculate percentile for empty values")
    return statistics.quantiles(values, n=100, method="inclusive")[percentile_value - 1]


def sign_jwt(claims: dict[str, Any], secret: str) -> str:
    now = int(time.time())
    payload = {"iat": now, "exp": now + 3600, **claims}
    encoded_header = b64url_json({"alg": "HS256", "typ": "JWT"})
    encoded_payload = b64url_json(payload)
    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{b64url(signature)}"


def b64url_json(value: dict[str, Any]) -> str:
    return b64url(json.dumps(value, separators=(",", ":")).encode())


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


if __name__ == "__main__":
    main()
