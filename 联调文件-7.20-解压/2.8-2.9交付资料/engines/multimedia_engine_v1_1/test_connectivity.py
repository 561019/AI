from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"


def read_dotenv(path: Path = ENV_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_config() -> dict[str, str]:
    file_values = read_dotenv()
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


def normalize_chat_endpoint(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def normalize_anthropic_endpoint(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/messages"):
        return base
    if base.endswith("/v1"):
        return base + "/messages"
    return base + "/v1/messages"


def request_json(url: str, payload: dict[str, Any] | None, headers: dict[str, str] | None, timeout: int) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers or {"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8-sig")
        return json.loads(body) if body else {}


def test_kb(config: dict[str, str], timeout: int) -> dict[str, Any]:
    kb_base = config["KB_BASE"].rstrip("/")
    health_url = kb_base + "/api/health"
    materials_url = kb_base + "/api/kb/task-materials"
    health = request_json(health_url, None, None, timeout)
    package = request_json(
        materials_url,
        {
            "actor_id": "U001",
            "task_type": "multimedia_poster",
            "query": "智能监测设备 海报 Logo 产品图 爆款案例 品牌规范",
            "top_k": 5,
            "include_templates": True,
        },
        {"Content-Type": "application/json"},
        timeout,
    )
    materials = package.get("materials") or []
    return {
        "ok": True,
        "health_url": health_url,
        "materials_url": materials_url,
        "health": health,
        "readiness": package.get("readiness"),
        "material_count": len(materials),
        "returned_types": package.get("returned_types", []),
        "first_material": materials[0].get("title") if materials else None,
    }


def test_llm(config: dict[str, str], timeout: int) -> dict[str, Any]:
    protocol = (config["LLM_PROTOCOL"] or "openai_compatible").strip().lower()
    missing = [key for key in ("LITELLM_BASE", "KIMI_MODEL", "LITELLM_KEY") if not config.get(key)]
    if missing:
        return {"ok": False, "error": "LLM 配置不完整", "missing": missing}
    if protocol == "openai_compatible":
        return test_openai_compatible(config, timeout)
    if protocol == "anthropic":
        return test_anthropic_compatible(config, timeout)
    return {"ok": False, "error": f"暂不支持的 LLM_PROTOCOL：{protocol}"}


def test_openai_compatible(config: dict[str, str], timeout: int) -> dict[str, Any]:
    endpoint = normalize_chat_endpoint(config["LITELLM_BASE"])
    payload = {
        "model": config["KIMI_MODEL"],
        "messages": [
            {"role": "system", "content": "你是接口连通性测试助手，只返回 JSON。"},
            {"role": "user", "content": '请只回复：{"ok":true,"message":"connected"}'},
        ],
        "temperature": 0,
        "max_tokens": 80,
    }
    data = request_json(
        endpoint,
        payload,
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['LITELLM_KEY']}",
        },
        timeout,
    )
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return {
        "ok": True,
        "protocol": "openai_compatible",
        "endpoint": endpoint,
        "model": config["KIMI_MODEL"],
        "content_preview": content[:200],
    }


def test_anthropic_compatible(config: dict[str, str], timeout: int) -> dict[str, Any]:
    endpoint = normalize_anthropic_endpoint(config["LITELLM_BASE"])
    payload = {
        "model": config["KIMI_MODEL"],
        "system": "你是接口连通性测试助手，只返回 JSON。",
        "messages": [{"role": "user", "content": '请只回复：{"ok":true,"message":"connected"}'}],
        "temperature": 0,
        "max_tokens": 80,
    }
    data = request_json(
        endpoint,
        payload,
        {
            "Content-Type": "application/json",
            "x-api-key": config["LITELLM_KEY"],
            "anthropic-version": "2023-06-01",
        },
        timeout,
    )
    blocks = data.get("content") or []
    text_parts = [
        block.get("text", "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    content = "\n".join(part for part in text_parts if part)
    return {
        "ok": True,
        "protocol": "anthropic",
        "endpoint": endpoint,
        "model": config["KIMI_MODEL"],
        "content_preview": content[:200],
    }


def run_test(name: str, fn, config: dict[str, str], timeout: int) -> dict[str, Any]:
    try:
        return fn(config, timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {exc.code}", "body": body[:1000]}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": f"{name} 接口不可用：{exc.reason}"}
    except TimeoutError as exc:
        return {"ok": False, "error": f"{name} 连接超时：{exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def print_human(results: dict[str, Any]) -> None:
    config = results["config"]
    print("配置来源:", str(ENV_PATH))
    print("KB_BASE:", config["kb_base"])
    print("LLM_PROTOCOL:", config["llm_protocol"])
    print("LITELLM_BASE:", config["litellm_base"] or "-")
    print("KIMI_MODEL:", config["kimi_model"] or "-")
    print("LITELLM_KEY:", config["litellm_key_masked"] or "-")
    print()
    if "kb" in results:
        kb = results["kb"]
        print("[知识库连接]", "通过" if kb.get("ok") else "失败")
        print(json.dumps(kb, ensure_ascii=False, indent=2))
        print()
    if "llm" in results:
        llm = results["llm"]
        print("[LLM 连接]", "通过" if llm.get("ok") else "失败")
        print(json.dumps(llm, ensure_ascii=False, indent=2))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="测试多媒体生成引擎 v1.1 的知识库和 LLM 接口连通性。")
    parser.add_argument("--kb-only", action="store_true", help="只测试知识库接口")
    parser.add_argument("--llm-only", action="store_true", help="只测试 LLM 接口")
    parser.add_argument("--timeout", type=int, default=15, help="单个请求超时时间，默认 15 秒")
    parser.add_argument("--json", action="store_true", help="以 JSON 形式输出结果")
    args = parser.parse_args()

    config = get_config()
    results: dict[str, Any] = {
        "config": {
            "kb_base": config["KB_BASE"],
            "llm_protocol": config["LLM_PROTOCOL"],
            "litellm_base": config["LITELLM_BASE"],
            "kimi_model": config["KIMI_MODEL"],
            "litellm_key_masked": mask_secret(config["LITELLM_KEY"]),
        }
    }
    do_kb = not args.llm_only
    do_llm = not args.kb_only
    if do_kb:
        results["kb"] = run_test("知识库", test_kb, config, args.timeout)
    if do_llm:
        results["llm"] = run_test("LLM", test_llm, config, args.timeout)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_human(results)

    checks = [value for key, value in results.items() if key != "config"]
    return 0 if checks and all(item.get("ok") for item in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
