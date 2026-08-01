from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"


def load_local_env(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_langfuse_config() -> dict[str, str | bool | None]:
    load_local_env()
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    base_url = os.getenv("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
    return {
        "base_url": base_url,
        "public_key_set": bool(public_key),
        "secret_key_set": bool(secret_key),
        "public_key_preview": _preview(public_key),
        "ready": bool(public_key and secret_key and base_url),
    }


def get_langfuse_credentials() -> dict[str, str]:
    load_local_env()
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    base_url = os.getenv("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
    if not public_key or not secret_key:
        raise RuntimeError("Langfuse credentials are not configured")
    return {
        "base_url": base_url.rstrip("/"),
        "public_key": public_key,
        "secret_key": secret_key,
    }


def get_llm_config() -> dict[str, str | bool | None]:
    load_local_env()
    provider = (os.getenv("LLM_PROVIDER") or "builtin").lower()
    api_key = (
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("MOONSHOT_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    base_url = (
        os.getenv("DEEPSEEK_BASE_URL")
        or os.getenv("MOONSHOT_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or _default_base_url(provider)
    )
    model = (
        os.getenv("DEEPSEEK_MODEL")
        or os.getenv("KIMI_MODEL")
        or os.getenv("OPENAI_MODEL")
        or _default_model(provider)
    )
    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key_set": bool(api_key),
        "api_key_preview": _preview(api_key),
        "ready": provider in {"kimi", "deepseek"} and bool(api_key and base_url and model),
    }


def get_kimi_config() -> dict[str, str | bool | None]:
    return get_llm_config()


def get_llm_credentials() -> dict[str, str]:
    load_local_env()
    provider = (os.getenv("LLM_PROVIDER") or "builtin").lower()
    api_key = (
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("MOONSHOT_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    base_url = (
        os.getenv("DEEPSEEK_BASE_URL")
        or os.getenv("MOONSHOT_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or _default_base_url(provider)
    )
    model = (
        os.getenv("DEEPSEEK_MODEL")
        or os.getenv("KIMI_MODEL")
        or os.getenv("OPENAI_MODEL")
        or _default_model(provider)
    )
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY, MOONSHOT_API_KEY, or OPENAI_API_KEY is not configured")
    return {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "model": model,
        "provider": provider,
    }


def get_kimi_credentials() -> dict[str, str]:
    return get_llm_credentials()


def use_remote_generation() -> bool:
    load_local_env()
    return (os.getenv("LLM_PROVIDER") or "").lower() in {"kimi", "deepseek"}


def use_kimi_generation() -> bool:
    return use_remote_generation()


def _default_base_url(provider: str) -> str:
    if provider == "deepseek":
        return "https://api.deepseek.com"
    if provider == "kimi":
        return "https://api.moonshot.cn/v1"
    return "https://api.moonshot.cn/v1"


def _default_model(provider: str) -> str:
    if provider == "deepseek":
        return "deepseek-v4-flash"
    if provider == "kimi":
        return "kimi-k2.6"
    return "kimi-k2.6"


def _preview(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"
