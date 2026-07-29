from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SemanticCapability:
    engine_code: str
    task_type: str
    task_name: str
    description: str
    examples: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)


class SemanticCapabilityCatalog:
    """Loads semantic capability definitions from configuration."""

    def __init__(self, capabilities: list[SemanticCapability]) -> None:
        self.capabilities = capabilities
        self._by_task_type = {capability.task_type: capability for capability in capabilities}

    @classmethod
    def from_default_file(cls) -> "SemanticCapabilityCatalog":
        return cls.from_file(default_semantic_capability_path())

    @classmethod
    def from_file(cls, path: Path) -> "SemanticCapabilityCatalog":
        payload = load_yaml_subset(path)
        raw_capabilities = payload.get("capabilities", [])
        capabilities = [
            SemanticCapability(
                engine_code=str(item.get("engine_code", "")),
                task_type=str(item.get("task_type", "")),
                task_name=str(item.get("task_name", "") or item.get("task_type", "")),
                description=str(item.get("description", "")),
                examples=[str(value) for value in item.get("examples", [])],
                keywords=[str(value) for value in item.get("keywords", [])],
                required_inputs=[str(value) for value in item.get("required_inputs", [])],
            )
            for item in raw_capabilities
            if isinstance(item, dict)
        ]
        return cls(capabilities)

    def list_capabilities(self) -> list[SemanticCapability]:
        return list(self.capabilities)

    def get_by_task_type(self, task_type: str) -> SemanticCapability | None:
        return self._by_task_type.get(task_type)

    def required_inputs_for(self, task_type: str) -> list[str] | None:
        capability = self.get_by_task_type(task_type)
        if capability is None:
            return None
        return list(capability.required_inputs)


def default_semantic_capability_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "semantic_capabilities.yaml"


def load_yaml_subset(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")

    try:
        import yaml  # type: ignore

        payload = yaml.safe_load(text)
        return payload if isinstance(payload, dict) else {}
    except ModuleNotFoundError:
        return parse_semantic_capability_yaml(text)


def parse_semantic_capability_yaml(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by semantic_capabilities.yaml."""

    capabilities: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_list_key: str | None = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        stripped = raw_line.strip()
        if stripped == "capabilities:":
            continue

        if stripped.startswith("- ") and raw_line.startswith("  - "):
            if current is not None:
                capabilities.append(current)
            current = {}
            current_list_key = None
            content = stripped[2:].strip()
            if content:
                key, value = split_yaml_key_value(content)
                current[key] = parse_scalar(value)
            continue

        if current is None:
            continue

        if stripped.startswith("- ") and current_list_key:
            current.setdefault(current_list_key, []).append(parse_scalar(stripped[2:].strip()))
            continue

        if stripped.endswith(":"):
            current_list_key = stripped[:-1]
            current[current_list_key] = []
            continue

        key, value = split_yaml_key_value(stripped)
        current[key] = parse_scalar(value)
        current_list_key = None

    if current is not None:
        capabilities.append(current)

    return {"capabilities": capabilities}


def split_yaml_key_value(text: str) -> tuple[str, str]:
    if ":" not in text:
        return text, ""
    key, value = text.split(":", 1)
    return key.strip(), value.strip()


def parse_scalar(value: str) -> Any:
    if value == "[]":
        return []
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
