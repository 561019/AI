from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4


HOST = "0.0.0.0"
PORT = 8001
EMBEDDING_DIMENSION = 1024
BGE_BASE_ZH_DIMENSION = 768

MODELS = [
    {
        "id": "BAAI/bge-base-zh-v1.5",
        "object": "model",
        "created": 0,
        "owned_by": "local-test",
    },
    {
        "id": "bge-m3",
        "object": "model",
        "created": 0,
        "owned_by": "local-test",
    },
    {
        "id": "qwen-32b",
        "object": "model",
        "created": 0,
        "owned_by": "local-test",
    },
]

CONCEPT_BLOCKS = {
    "report": range(0, 32),
    "qa": range(64, 96),
    "data": range(128, 160),
    "content": range(192, 224),
    "workflow": range(256, 288),
    "calculation": range(320, 352),
    "analysis": range(384, 416),
    "unknown": range(960, 992),
}

CONCEPT_KEYWORDS = {
    "report": [
        "报告",
        "报表",
        "销售",
        "业绩",
        "公司表现",
        "business report",
        "report generation",
        "generate a business report",
    ],
    "qa": [
        "问答",
        "问题",
        "查询",
        "怎么处理",
        "政策",
        "知识",
        "question",
        "answer",
        "intelligent qa",
    ],
    "data": [
        "数据处理",
        "汇总",
        "统计",
        "表",
        "分类",
        "求和",
        "聚合",
        "清洗",
        "process explicit data",
        "aggregation",
    ],
    "content": [
        "内容",
        "创作",
        "写",
        "说明",
        "通知",
        "文案",
        "create business content",
        "content creation",
    ],
    "workflow": [
        "流程",
        "审批",
        "自动处理",
        "workflow",
    ],
    "calculation": [
        "提成",
        "佣金",
        "奖金",
        "销售人员奖金",
        "怎么算",
        "计算",
        "核算",
        "测算",
        "算一下",
        "rule calculation",
        "commission",
    ],
    "analysis": [
        "经营",
        "经营情况",
        "业务情况",
        "经营分析",
        "表现",
        "怎么样",
        "原因",
        "归因",
        "异常",
        "风险",
        "趋势",
        "洞察",
        "problem analysis",
    ],
}


class LocalModelHandler(BaseHTTPRequestHandler):
    server_version = "LocalOpenAICompatibleTestModel/0.1"

    def do_GET(self) -> None:
        if self.path in {"/health", "/healthz", "/ready"}:
            self._send_json({"status": "ok", "service": "local-test-model"})
            return

        if self.path.rstrip("/") == "/v1/models":
            self._send_json({"object": "list", "data": MODELS})
            return

        self._send_json({"error": {"message": "not found"}}, status=404)

    def do_POST(self) -> None:
        payload = self._read_json()
        path = self.path.rstrip("/")

        if path == "/v1/embeddings":
            self._handle_embeddings(payload)
            return

        if path in {"/v1/chat/completions", "/v1/chat"}:
            self._handle_chat(payload)
            return

        if path in {"/v1/rerank", "/rerank"}:
            self._handle_rerank(payload)
            return

        self._send_json({"error": {"message": "not found"}}, status=404)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _handle_embeddings(self, payload: dict[str, Any]) -> None:
        raw_input = payload.get("input", [])
        if isinstance(raw_input, str):
            texts = [raw_input]
        elif isinstance(raw_input, list):
            texts = [str(item) for item in raw_input]
        else:
            self._send_json({"error": {"message": "input must be string or list"}}, status=400)
            return

        model = str(payload.get("model") or "bge-m3")
        dimension = embedding_dimension_for_model(model)
        data = [
            {
                "object": "embedding",
                "index": index,
                "embedding": build_embedding(text, dimension=dimension),
            }
            for index, text in enumerate(texts)
        ]

        self._send_json(
            {
                "object": "list",
                "model": model,
                "data": data,
                "usage": {
                    "prompt_tokens": sum(max(1, len(text)) for text in texts),
                    "total_tokens": sum(max(1, len(text)) for text in texts),
                },
            },
        )

    def _handle_chat(self, payload: dict[str, Any]) -> None:
        messages = payload.get("messages") or []
        prompt = "\n".join(str(message.get("content", "")) for message in messages if isinstance(message, dict))
        implicit_extraction = "implicit task candidate detector" in prompt.lower()
        user_text = (
            extract_prompt_value(prompt, "User text")
            if implicit_extraction
            else extract_prompt_value(prompt, "User input")
        ) or prompt
        user_id = extract_prompt_value(prompt, "User id") or "test_user"
        if implicit_extraction:
            response_payload = build_implicit_task_candidates(user_text=user_text)
        else:
            task_list = build_task_list(user_text=user_text, user_id=user_id)
            if "evidence_spans" in prompt and "registered capabilities" in prompt.lower():
                response_payload = {
                    "result": task_list,
                    "evidence_spans": [
                        {"task_index": index, "evidence_span": user_text}
                        for index, _ in enumerate(task_list["tasks"])
                    ],
                }
            else:
                response_payload = task_list
        content = json.dumps(response_payload, ensure_ascii=False)

        self._send_json(
            {
                "id": f"chatcmpl-{uuid4()}",
                "object": "chat.completion",
                "created": int(datetime.now(UTC).timestamp()),
                "model": str(payload.get("model") or "qwen-32b"),
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": content,
                        },
                    },
                ],
                "usage": {
                    "prompt_tokens": max(1, len(prompt)),
                    "completion_tokens": len(content),
                    "total_tokens": max(1, len(prompt)) + len(content),
                },
            },
        )

    def _handle_rerank(self, payload: dict[str, Any]) -> None:
        documents = payload.get("documents") or []
        self._send_json(
            {
                "results": [
                    {
                        "index": index,
                        "relevance_score": max(0.0, 1.0 - index * 0.05),
                    }
                    for index, _ in enumerate(documents)
                ],
            },
        )

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw_body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_embedding(text: str, *, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    weights = classify_text(text)
    vector = [0.0] * dimension

    for concept, weight in weights.items():
        indices = concept_blocks(dimension)[concept]
        value = weight / math.sqrt(len(indices))
        for index in indices:
            vector[index] += value

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [round(value / norm, 8) for value in vector]


def embedding_dimension_for_model(model: str) -> int:
    if model == "BAAI/bge-base-zh-v1.5":
        return BGE_BASE_ZH_DIMENSION
    return EMBEDDING_DIMENSION


def concept_blocks(dimension: int) -> dict[str, range]:
    if dimension >= EMBEDDING_DIMENSION:
        return CONCEPT_BLOCKS
    return {
        "report": range(0, 32),
        "qa": range(64, 96),
        "data": range(128, 160),
        "content": range(192, 224),
        "workflow": range(256, 288),
        "calculation": range(320, 352),
        "analysis": range(384, 416),
        "unknown": range(max(0, dimension - 64), max(0, dimension - 32)),
    }


def classify_text(text: str) -> dict[str, float]:
    normalized = text.strip().lower()
    weights: dict[str, float] = {}

    for concept, keywords in CONCEPT_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword.lower() in normalized)
        if score:
            weights[concept] = 1.0 + min(score, 4) * 0.25

    if not weights:
        weights["unknown"] = 1.0

    return weights


def build_task_list(*, user_text: str, user_id: str) -> dict[str, Any]:
    concept = max(classify_text(user_text), key=classify_text(user_text).get)
    if concept == "unknown":
        return {
            "request_id": str(uuid4()),
            "original_text": user_text,
            "intent_category": "待澄清",
            "tasks": [],
            "clarification_required": True,
            "clarification_questions": ["当前请求不属于已注册能力，请确认需要完成的业务操作。"],
            "analysis_level": 3,
            "overall_confidence": 0,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    task_type, task_name, intent_category, target_engine, engine_code = task_for_concept(concept)
    confidence = 0.82

    return {
        "request_id": str(uuid4()),
        "original_text": user_text,
        "intent_category": intent_category,
        "tasks": [
            {
                "task_id": str(uuid4()),
                "task_name": task_name,
                "task_type": task_type,
                "target_engine": target_engine,
                "engine_code": engine_code,
                "required_inputs": [f"source_text:{user_text}", "local_test_model:true"],
                "missing_inputs": [],
                "dependencies": [],
                "execution_order": 1,
                "confidence": confidence,
            },
        ],
        "clarification_required": False,
        "clarification_questions": [],
        "analysis_level": 3,
        "overall_confidence": confidence,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def build_implicit_task_candidates(*, user_text: str) -> dict[str, Any]:
    normalized = user_text.strip()
    candidates: list[dict[str, Any]] = []
    request_signal = bool(
        re.search(r"要一份|需要一份|希望看到|想拿到|能看出|交付|给管理层|给领导", normalized)
    )
    if request_signal and re.search(r"为什么|原因|下滑|下降|异常", normalized):
        candidates.append(
            {
                "normalized_text": "分析销售下降原因",
                "evidence_span": normalized,
                "confidence": 0.84,
                "depends_on_previous": False,
            }
        )
    if request_signal and re.search(r"材料|报告|文档|PPT|说明", normalized):
        candidates.append(
            {
                "normalized_text": "生成管理层分析报告",
                "evidence_span": normalized,
                "confidence": 0.82,
                "depends_on_previous": bool(candidates),
            }
        )
    if candidates:
        return {"candidates": candidates, "unsupported": False, "reason": None}

    concept = max(classify_text(normalized), key=classify_text(normalized).get)
    unsupported = request_signal and concept == "unknown"
    return {
        "candidates": [],
        "unsupported": unsupported,
        "reason": "no_registered_capability" if unsupported else None,
    }


def task_for_concept(concept: str) -> tuple[str, str, str, str, str]:
    mapping = {
        "report": ("DOCUMENT_GENERATE", "生成业务文档", "文档生成型", "内容产出引擎", "ENG_CONTENT_OUTPUT"),
        "qa": ("QUESTION_ANSWER", "智能问答", "智能问答型", "知识库问答引擎", "ENG_KNOWLEDGE_QA"),
        "data": ("DATA_AGGREGATION_SUMMARY", "数据处理汇总", "数据分析型", "数据归集聚合引擎", "ENG_DATA_COLLECTION_AGGREGATION"),
        "content": ("CONTENT_GENERATE", "内容生成", "内容生成型", "内容产出引擎", "ENG_CONTENT_OUTPUT"),
        "calculation": ("RULE_CALCULATION_COMMISSION", "计算销售提成", "规则计算型", "规则计算引擎", "ENG_RULE_CALCULATION"),
        "analysis": ("DATA_ANALYSIS_PROBLEM", "经营分析", "数据分析型", "分析预测引擎", "ENG_ANALYTICS_FORECASTING"),
    }
    return mapping.get(concept, ("QUESTION_ANSWER", "智能问答", "智能问答型", "知识库问答引擎", "ENG_KNOWLEDGE_QA"))


def extract_prompt_value(prompt: str, label: str) -> str | None:
    pattern = rf"{re.escape(label)}:\s*\n(?P<value>.*?)(?:\n\s*\n|$)"
    match = re.search(pattern, prompt, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return match.group("value").strip()


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), LocalModelHandler)
    print(f"Local OpenAI-compatible test model service listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
