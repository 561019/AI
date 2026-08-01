"""通过 LiteLLM 的 Anthropic Messages 协议进行多轮命令行对话。"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = os.getenv("LITELLM_BASE", "http://221.7.147.130:4000/").rstrip("/")
MODEL = os.getenv("KIMI_MODEL", "kimi")
API_KEY = os.getenv("LITELLM_KEY", "sk-litellm-master-change-me")


def chat(messages: list[dict[str, str]]) -> str:
    """发送完整对话历史，返回模型的文本回复。"""
    payload = {
        "model": MODEL,
        "max_tokens": 2048,
        "messages": messages,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "anthropic-version": "2023-06-01",
    }
    # 某些内网 LiteLLM 不校验密钥，所以允许 LITELLM_KEY 为空。
    if API_KEY:
        headers["x-api-key"] = API_KEY

    request = Request(
        f"{BASE_URL}/v1/messages",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API 返回 HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"无法连接 API: {exc.reason}") from exc

    texts = [
        block.get("text", "")
        for block in result.get("content", [])
        if block.get("type") == "text"
    ]
    answer = "".join(texts).strip()
    if not answer:
        raise RuntimeError(f"API 未返回文本内容: {result}")
    return answer


def main() -> None:
    messages: list[dict[str, str]] = []
    print(f"已连接模型 {MODEL}。输入 exit 或 quit 退出，输入 clear 清空上下文。")

    while True:
        try:
            user_input = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("再见！")
            break
        if user_input.lower() == "clear":
            messages.clear()
            print("上下文已清空。")
            continue

        messages.append({"role": "user", "content": user_input})
        try:
            answer = chat(messages)
        except RuntimeError as exc:
            messages.pop()  # 请求失败时不把本轮问题留在历史中
            print(f"错误：{exc}")
            continue

        print(f"Kimi：{answer}")
        messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()
