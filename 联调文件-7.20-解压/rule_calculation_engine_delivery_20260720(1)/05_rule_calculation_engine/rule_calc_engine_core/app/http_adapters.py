from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .adapters import SQLiteBusinessDataProvider
from .ports import (
    CodeArtifactReference,
    DigitalAssetCandidateRequest,
    SandboxRunRequest,
    SandboxRunResult,
)


SANDBOX_WORKER = r"""
import json
import sys

payload = json.loads(sys.stdin.read())
safe_builtins = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}
namespace = {"__builtins__": safe_builtins}
exec(compile(payload["code"], "<candidate-asset>", "exec"), namespace, namespace)
result = namespace[payload["entrypoint"]](payload["data"])
sys.stdout.write(json.dumps(result, ensure_ascii=False))
"""


class HttpDigitalAssetAdapter:
    """Test adapter for the independent Digital Asset Engine simulator."""

    def __init__(self, base_url: str, timeout_seconds: int = 65) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request_candidate_code(
        self, request: DigitalAssetCandidateRequest
    ) -> CodeArtifactReference:
        body = json.dumps(
            {
                "trace_id": request.trace_id,
                "request_id": request.request_id,
                "candidate_request_id": request.candidate_request_id,
                "business_type": request.business_type,
                "objective": request.objective,
                "input_schema": request.input_schema,
                "output_schema": request.output_schema,
                "assumptions": request.assumptions,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        http_request = Request(
            f"{self.base_url}/api/v1/candidate-assets",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as error:
            raise ConnectionError(f"Digital Asset Engine test service is unavailable: {error}") from error
        try:
            return CodeArtifactReference(**payload)
        except TypeError as error:
            raise ValueError("Digital Asset Engine returned an invalid candidate reference.") from error


class RestrictedLocalSandboxAdapter:
    """L1.14 contract simulator using an isolated, time-limited child process."""

    def __init__(self, database_path: Path, timeout_seconds: int = 3) -> None:
        self.data_provider = SQLiteBusinessDataProvider(database_path)
        self.timeout_seconds = timeout_seconds

    def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        run_id = f"SBX-{uuid4().hex[:12].upper()}"
        try:
            code, manifest = self._fetch_candidate(request.artifact)
            self._validate_candidate(code, request.artifact.entrypoint)
            rows, _ = self.data_provider.read(request.data_reference, None, None)
            if not rows:
                return self._failure(
                    run_id, request, "SANDBOX_DATA_NOT_FOUND", "The authorized data reference could not be resolved."
                )
            timeout = min(
                self.timeout_seconds,
                int(request.resource_limits.get("timeout_seconds", self.timeout_seconds)),
            )
            completed = subprocess.run(
                [sys.executable, "-I", "-S", "-c", SANDBOX_WORKER],
                input=json.dumps(
                    {
                        "code": code,
                        "entrypoint": request.artifact.entrypoint,
                        "data": rows,
                    },
                    ensure_ascii=False,
                ),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            if completed.returncode != 0:
                return self._failure(
                    run_id,
                    request,
                    "SANDBOX_CODE_FAILED",
                    completed.stderr.strip() or "Candidate code exited with a non-zero status.",
                )
            result = json.loads(completed.stdout)
            if not isinstance(result, dict):
                return self._failure(
                    run_id, request, "SANDBOX_RESULT_INVALID", "Candidate code did not return an object."
                )
            required_fields = request.resource_limits.get("required_output_fields", [])
            missing = sorted(set(required_fields).difference(result))
            digest_matches = manifest.get("code_digest") == request.artifact.code_digest
            validation = [
                {
                    "name": "candidate_digest_match",
                    "passed": digest_matches,
                    "detail": "The fetched candidate code matches the Digital Asset Engine reference.",
                },
                {
                    "name": "required_output_fields",
                    "passed": not missing,
                    "detail": (
                        "All required output fields are present."
                        if not missing
                        else f"Missing output fields: {', '.join(missing)}"
                    ),
                },
                {
                    "name": "restricted_process_completed",
                    "passed": True,
                    "detail": "The local L1.14 simulator completed within its child-process timeout.",
                },
            ]
            return SandboxRunResult(
                run_id=run_id,
                artifact_ref=request.artifact.artifact_ref,
                succeeded=all(item["passed"] for item in validation),
                detail="The local L1.14 Agent execution sandbox simulator completed the candidate run.",
                result=result,
                validation_evidence=validation,
                environment="local-restricted-subprocess-simulator",
                reason_code=None if all(item["passed"] for item in validation) else "SANDBOX_VALIDATION_FAILED",
            )
        except subprocess.TimeoutExpired:
            return self._failure(
                run_id, request, "SANDBOX_TIMEOUT", "Candidate code exceeded the local sandbox timeout."
            )
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            return self._failure(run_id, request, "SANDBOX_EXECUTION_FAILED", str(error))

    @staticmethod
    def _fetch_candidate(artifact: CodeArtifactReference) -> tuple[str, dict[str, Any]]:
        if not artifact.content_url:
            raise ValueError("The candidate asset does not provide a content URL for the sandbox adapter.")
        with urlopen(artifact.content_url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        code = payload.get("code")
        manifest = payload.get("manifest")
        if not isinstance(code, str) or not isinstance(manifest, dict):
            raise ValueError("The candidate asset content contract is invalid.")
        actual_digest = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
        if actual_digest != artifact.code_digest:
            raise ValueError("The candidate code digest does not match its reference.")
        return code, manifest

    @staticmethod
    def _validate_candidate(code: str, entrypoint: str) -> None:
        tree = ast.parse(code)
        banned_nodes = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef)
        banned_calls = {"eval", "exec", "compile", "open", "input", "getattr", "setattr", "delattr"}
        functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        if entrypoint not in functions:
            raise ValueError("Candidate entrypoint is missing.")
        for node in ast.walk(tree):
            if isinstance(node, banned_nodes):
                raise ValueError(f"Prohibited syntax in candidate code: {type(node).__name__}.")
            if isinstance(node, ast.Name) and node.id.startswith("__"):
                raise ValueError("Candidate code contains a prohibited dunder name.")
            if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                raise ValueError("Candidate code contains a prohibited dunder attribute.")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in banned_calls:
                raise ValueError(f"Candidate code calls prohibited function {node.func.id!r}.")

    @staticmethod
    def _failure(
        run_id: str, request: SandboxRunRequest, reason_code: str, detail: str
    ) -> SandboxRunResult:
        return SandboxRunResult(
            run_id=run_id,
            artifact_ref=request.artifact.artifact_ref,
            succeeded=False,
            detail=detail,
            result={},
            validation_evidence=[],
            environment="local-restricted-subprocess-simulator",
            reason_code=reason_code,
        )
