import json
from pathlib import Path

from pydantic import ValidationError

from app.integrations.models.base import BaseModelGateway
from app.schemas.llm import NeedConfirmationResult
from app.schemas.task import TaskList


class LLMIntentAnalyzer:
    """Level 3 analyzer for complex intent understanding."""

    def __init__(
        self,
        *,
        model_gateway: BaseModelGateway,
        prompt_path: Path | None = None,
    ) -> None:
        self.model_gateway = model_gateway
        self.prompt_path = prompt_path or self._default_prompt_path()

    def analyze(
        self,
        text: str,
        *,
        user_id: str = "unknown",
    ) -> TaskList | NeedConfirmationResult:
        prompt = self._render_prompt(text=text, user_id=user_id)
        raw_response = self.model_gateway.chat(
            [
                {"role": "system", "content": prompt},
            ],
        )

        task_list = self._parse_task_list(raw_response)
        if task_list is not None:
            return task_list

        repaired_response = self._repair_json(
            raw_response=raw_response,
            user_id=user_id,
        )
        repaired_task_list = self._parse_task_list(repaired_response)
        if repaired_task_list is not None:
            return repaired_task_list

        return NeedConfirmationResult(
            reason="invalid_task_list_json",
            raw_response=repaired_response,
        )

    def _render_prompt(self, *, text: str, user_id: str) -> str:
        template = self.prompt_path.read_text(encoding="utf-8")
        template = (
            template.replace("IntentAnalysisResult JSON Schema:", "TaskList JSON Schema:")
            .replace("{{INTENT_ANALYSIS_RESULT_JSON_SCHEMA}}", "{{TASKLIST_JSON_SCHEMA}}")
        )
        return (
            template
            .replace("{{TASKLIST_JSON_SCHEMA}}", json.dumps(TaskList.model_json_schema(), ensure_ascii=False))
            .replace("{{USER_TEXT}}", text)
            .replace("{{USER_ID}}", user_id)
        )

    def _repair_json(self, *, raw_response: str, user_id: str) -> str:
        repair_prompt = (
            "Repair the following model output into valid JSON that conforms to the TaskList schema. "
            "Return JSON only. analysis_level must be 3. "
            f"user_id must be {user_id!r}.\n\n"
            f"TaskList JSON Schema:\n{json.dumps(TaskList.model_json_schema(), ensure_ascii=False)}\n\n"
            f"Invalid output:\n{raw_response}"
        )
        return self.model_gateway.chat(
            [
                {"role": "system", "content": repair_prompt},
            ],
        )

    def _parse_task_list(self, raw_response: str) -> TaskList | None:
        try:
            payload = json.loads(self._extract_json(raw_response))
            return TaskList.model_validate(payload)
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError):
            return None

    def _extract_json(self, raw_response: str) -> str:
        text = raw_response.strip()

        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("No JSON object found.")

        return text[start : end + 1]

    def _default_prompt_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "prompts" / "legacy_tasklist_prompt.txt"
