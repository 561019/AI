from __future__ import annotations

import json
from urllib.request import Request, urlopen


BASE = "http://127.0.0.1:8020"


def get(path: str) -> dict:
    with urlopen(BASE + path, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post(path: str, payload: dict, timeout: int = 120) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(BASE + path, data=body, method="POST", headers={"Content-Type": "application/json; charset=utf-8"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


if __name__ == "__main__":
    print(json.dumps(get("/health"), ensure_ascii=False, indent=2))
    result = post(
        "/api/flow/start",
        {
            "actor_id": "U001",
            "workflow_type": "media_only",
            "requirement": "请根据智能监测设备资料生成一份产品海报制作方案和提示词。",
            "task_type": "multimedia_poster",
            "capability_id": "text_to_image",
            "output_type": "poster_plan",
            "top_k": 5,
            "use_llm": False,
            "review_policy": "always",
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
