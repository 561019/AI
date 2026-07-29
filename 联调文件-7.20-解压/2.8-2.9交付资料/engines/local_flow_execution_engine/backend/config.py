from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

DEFAULTS = {
    "FLOW_PORT": "8020",
    "MEDIA_BASE": "http://127.0.0.1:8013",
    "CONTENT_BASE": "http://127.0.0.1:8011",
    "REQUEST_TIMEOUT_SECONDS": "90",
}


def _parse_env_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#") or "=" not in text:
        return None
    key, value = text.split("=", 1)
    return key.strip(), value.strip().strip('"').strip("'")


def read_env() -> dict[str, str]:
    values = dict(DEFAULTS)
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(line)
            if parsed:
                values[parsed[0]] = parsed[1]
    return values


def save_env(updates: dict[str, str | None]) -> dict[str, str]:
    values = read_env()
    for key, value in updates.items():
        env_key = key.upper()
        if env_key in DEFAULTS and value is not None:
            values[env_key] = str(value).strip()
    lines = [
        "# 本地流程执行引擎配置。只保存本地联调地址，不保存大模型密钥。",
        f"FLOW_PORT={values['FLOW_PORT']}",
        f"MEDIA_BASE={values['MEDIA_BASE']}",
        f"CONTENT_BASE={values['CONTENT_BASE']}",
        f"REQUEST_TIMEOUT_SECONDS={values['REQUEST_TIMEOUT_SECONDS']}",
        "",
    ]
    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")
    return values
