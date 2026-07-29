from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent
ARTIFACT_ROOT = ROOT / "artifacts"


def load_local_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_local_env()


class CandidateRequest(BaseModel):
    trace_id: str = Field(min_length=4, max_length=80)
    request_id: str = Field(min_length=4, max_length=80)
    candidate_request_id: str = Field(min_length=4, max_length=100)
    business_type: str = Field(min_length=2, max_length=100)
    objective: str = Field(min_length=4, max_length=1000)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)


class CandidateReference(BaseModel):
    candidate_request_id: str
    artifact_ref: str
    artifact_version: str
    source: str
    code_digest: str
    entrypoint: str
    generation_id: str
    content_url: str
    candidate_only: bool = True


app = FastAPI(title="Digital Asset Engine Test Service", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "digital-asset-simulator",
        "provider": os.getenv("DIGITAL_ASSET_PROVIDER", "mock"),
    }


@app.post("/api/v1/candidate-assets", response_model=CandidateReference)
def create_candidate(request: CandidateRequest) -> CandidateReference:
    provider = os.getenv("DIGITAL_ASSET_PROVIDER", "mock").strip().lower()
    try:
        generated = generate_with_deepseek(request) if provider == "deepseek" else mock_generation()
        code = generated["code"].strip()
        entrypoint = generated.get("entrypoint", "calculate").strip()
        validate_candidate_code(code, entrypoint)
    except (ValueError, HTTPError, URLError, TimeoutError) as error:
        raise HTTPException(status_code=502, detail=f"Candidate generation failed: {error}") from error

    generation_id = f"GEN-{uuid4().hex[:12].upper()}"
    artifact_dir = ARTIFACT_ROOT / generation_id
    artifact_dir.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    (artifact_dir / "candidate.py").write_text(code + "\n", encoding="utf-8")
    manifest = {
        "generation_id": generation_id,
        "trace_id": request.trace_id,
        "request_id": request.request_id,
        "candidate_request_id": request.candidate_request_id,
        "business_type": request.business_type,
        "provider": provider,
        "entrypoint": entrypoint,
        "code_digest": digest,
        "candidate_only": True,
        "explanation": generated.get("explanation", ""),
    }
    (artifact_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    content_url = f"http://127.0.0.1:8020/api/v1/assets/{generation_id}"
    return CandidateReference(
        candidate_request_id=request.candidate_request_id,
        artifact_ref=f"asset://candidate-python/{generation_id}",
        artifact_version="candidate-1",
        source=f"digital-asset-simulator:{provider}",
        code_digest=digest,
        entrypoint=entrypoint,
        generation_id=generation_id,
        content_url=content_url,
    )


@app.get("/api/v1/assets/{generation_id}")
def get_candidate(generation_id: str) -> dict[str, Any]:
    if not generation_id.startswith("GEN-") or not generation_id.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid generation ID.")
    artifact_dir = ARTIFACT_ROOT / generation_id
    code_path = artifact_dir / "candidate.py"
    manifest_path = artifact_dir / "manifest.json"
    if not code_path.exists() or not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Candidate asset not found.")
    return {
        "code": code_path.read_text(encoding="utf-8"),
        "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
    }


def mock_generation() -> dict[str, str]:
    return {
        "entrypoint": "calculate",
        "explanation": "Fixed candidate used when the DeepSeek provider is disabled.",
        "code": (
            "def calculate(data):\n"
            "    baseline_revenue = float(data[0]['baseline_revenue'])\n"
            "    revenue_change_rate = float(data[0]['revenue_change_rate'])\n"
            "    baseline_margin = float(data[0]['baseline_margin'])\n"
            "    adjusted_margin = float(data[0]['adjusted_margin'])\n"
            "    adjusted_revenue = baseline_revenue * (1 + revenue_change_rate)\n"
            "    gross_profit_change = adjusted_revenue * adjusted_margin - baseline_revenue * baseline_margin\n"
            "    return {\n"
            "        'adjusted_revenue': round(adjusted_revenue, 2),\n"
            "        'gross_profit_change': round(gross_profit_change, 2),\n"
            "    }\n"
        ),
    }


def generate_with_deepseek(request: CandidateRequest) -> dict[str, str]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is empty in the local .env file.")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
    system_prompt = (
        "You generate candidate Python for a controlled enterprise calculation sandbox. "
        "Return one JSON object with code, entrypoint, and explanation. "
        "The code must define calculate(data), use no imports, files, network, eval, exec, "
        "reflection, or dunder names, and return a JSON-serializable dictionary."
    )
    user_prompt = json.dumps(
        {
            "objective": request.objective,
            "input_schema": request.input_schema,
            "output_schema": request.output_schema,
            "assumptions": request.assumptions,
        },
        ensure_ascii=False,
    )
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
    ).encode("utf-8")
    http_request = Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(http_request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    generated = json.loads(content)
    if not isinstance(generated, dict):
        raise ValueError("The model response is not a JSON object.")
    return generated


def validate_candidate_code(code: str, entrypoint: str) -> None:
    tree = ast.parse(code)
    banned_nodes = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef)
    banned_calls = {"eval", "exec", "compile", "open", "input", "getattr", "setattr", "delattr"}
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    if entrypoint not in functions:
        raise ValueError(f"Candidate code does not define entrypoint {entrypoint!r}.")
    for node in ast.walk(tree):
        if isinstance(node, banned_nodes):
            raise ValueError(f"Candidate code contains prohibited syntax: {type(node).__name__}.")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("Candidate code contains a prohibited dunder name.")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("Candidate code contains a prohibited dunder attribute.")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in banned_calls:
            raise ValueError(f"Candidate code calls prohibited function {node.func.id!r}.")
