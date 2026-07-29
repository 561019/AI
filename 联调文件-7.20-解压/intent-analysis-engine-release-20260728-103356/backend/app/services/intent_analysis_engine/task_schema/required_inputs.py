from __future__ import annotations

from typing import Final


TASK_INPUT_ALIASES: Final[dict[str, list[str]]] = {
    "document_type": ["document_type", "content_type"],
    "file": ["file", "file_type", "source_file"],
    "statistical_range": ["statistical_range", "period", "time_range", "date_range"],
    "sales_data_source": ["sales_data_source", "data_source"],
    "data_source": ["data_source"],
}


def provided_input_keys(values: list[str]) -> set[str]:
    provided = set()
    for value in values:
        raw_value = str(value).strip()
        if ":" not in raw_value:
            continue
        key, actual_value = raw_value.split(":", 1)
        if key.strip() and actual_value.strip():
            provided.add(key)
    return provided


def input_is_provided(required_input: str, provided_inputs: set[str]) -> bool:
    accepted_keys = TASK_INPUT_ALIASES.get(required_input, [required_input])
    return any(key in provided_inputs for key in accepted_keys)


def canonical_input_name(input_name: str) -> str:
    normalized = str(input_name).strip()
    for canonical, aliases in TASK_INPUT_ALIASES.items():
        if normalized in aliases:
            return canonical
    return normalized
