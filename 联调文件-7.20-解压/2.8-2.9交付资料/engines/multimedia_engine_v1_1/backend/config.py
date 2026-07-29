from __future__ import annotations

from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def _read_dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for raw in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_config() -> dict[str, str]:
    file_values = _read_dotenv()
    return {
        "KB_BASE": os.environ.get("KB_BASE") or file_values.get("KB_BASE") or "http://127.0.0.1:8012",
        "LLM_PROTOCOL": os.environ.get("LLM_PROTOCOL") or file_values.get("LLM_PROTOCOL") or "openai_compatible",
        "LITELLM_BASE": os.environ.get("LITELLM_BASE") or file_values.get("LITELLM_BASE") or "",
        "KIMI_MODEL": os.environ.get("KIMI_MODEL") or file_values.get("KIMI_MODEL") or "",
        "LITELLM_KEY": os.environ.get("LITELLM_KEY") or file_values.get("LITELLM_KEY") or "",
    }


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return value[:2] + "***"
    return value[:4] + "***" + value[-4:]


def public_config() -> dict[str, object]:
    cfg = get_config()
    return {
        "kb_base": cfg["KB_BASE"],
        "llm_protocol": cfg["LLM_PROTOCOL"],
        "litellm_base": cfg["LITELLM_BASE"],
        "kimi_model": cfg["KIMI_MODEL"],
        "litellm_key_masked": mask_secret(cfg["LITELLM_KEY"]),
        "ready_for_llm": bool(cfg["LITELLM_BASE"] and cfg["KIMI_MODEL"] and cfg["LITELLM_KEY"]),
        "env_path": str(ENV_PATH),
    }


def save_config(values: dict[str, str | None]) -> None:
    current = _read_dotenv()
    mapping = {
        "kb_base": "KB_BASE",
        "llm_protocol": "LLM_PROTOCOL",
        "litellm_base": "LITELLM_BASE",
        "kimi_model": "KIMI_MODEL",
        "litellm_key": "LITELLM_KEY",
    }
    for field, key in mapping.items():
        value = values.get(field)
        if value is not None and value != "":
            current[key] = value
    ordered = ["KB_BASE", "LLM_PROTOCOL", "LITELLM_BASE", "KIMI_MODEL", "LITELLM_KEY"]
    lines = ["# v1.1 本地联调配置。不要把真实 key 提交或外发。"]
    for key in ordered:
        if key in current:
            lines.append(f"{key}={current[key]}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
