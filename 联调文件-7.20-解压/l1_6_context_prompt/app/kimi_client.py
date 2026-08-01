from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import get_llm_credentials


def generate_kimi_text(
    *,
    system_prompt: str,
    user_prompt: str,
    max_completion_tokens: int = 2048,
    temperature: float = 0.2,
    prompt_cache_key: str | None = None,
    safety_identifier: str | None = None,
) -> dict[str, Any]:
    return generate_llm_text(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_completion_tokens=max_completion_tokens,
        temperature=temperature,
        prompt_cache_key=prompt_cache_key,
        safety_identifier=safety_identifier,
    )


def generate_llm_text(
    *,
    system_prompt: str,
    user_prompt: str,
    max_completion_tokens: int = 2048,
    temperature: float = 0.2,
    prompt_cache_key: str | None = None,
    safety_identifier: str | None = None,
) -> dict[str, Any]:
    credentials = get_llm_credentials()
    payload: dict[str, Any] = {
        "model": credentials["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_completion_tokens": max_completion_tokens,
        "temperature": temperature,
    }
    if prompt_cache_key:
        payload["prompt_cache_key"] = prompt_cache_key
    if safety_identifier:
        payload["safety_identifier"] = safety_identifier

    if credentials.get("provider") == "deepseek":
        payload.pop("prompt_cache_key", None)
        payload.pop("safety_identifier", None)

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{credentials['base_url']}/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {credentials['api_key']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM API error {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"LLM API request failed: {exc}") from exc

    result = json.loads(raw)
    content = ((result.get("choices") or [{}])[0].get("message") or {}).get("content")
    if not content:
        raise RuntimeError("Kimi API returned an empty message")
    return {
        "content": content,
        "provider": credentials.get("provider"),
        "model": result.get("model") or credentials["model"],
        "response_id": result.get("id"),
        "usage": result.get("usage") or {},
        "raw": result,
    }


def json_for_prompt(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
