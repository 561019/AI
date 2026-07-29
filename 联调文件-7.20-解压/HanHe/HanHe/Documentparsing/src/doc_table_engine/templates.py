from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ParsedContent, ParsedValue


@dataclass(frozen=True)
class FieldRule:
    name: str
    target_field: str
    selector: dict[str, Any]
    required: bool = False


@dataclass(frozen=True)
class ParseTemplate:
    template_id: str
    version: str
    document_type: str
    fields: tuple[FieldRule, ...]

    @classmethod
    def load(cls, path: Path) -> "ParseTemplate":
        data = json.loads(path.read_text(encoding="utf-8"))
        fields = tuple(FieldRule(
            name=item["name"],
            target_field=item["target_field"],
            selector=item["selector"],
            required=bool(item.get("required", False)),
        ) for item in data["fields"])
        return cls(data["template_id"], str(data["version"]), data["document_type"], fields)


class TemplateExtractor:
    def extract(self, content: ParsedContent, template: ParseTemplate) -> list[ParsedValue]:
        values = [value for table in content.tables for value in table.values]
        blocks = [*content.text_blocks, *values]
        extracted: list[ParsedValue] = []
        for rule in template.fields:
            selector_type = rule.selector.get("type")
            match: ParsedValue | None = None
            raw_value: Any = None
            if selector_type == "cell":
                sheet = rule.selector.get("sheet")
                cell = rule.selector["cell"]
                match = next((value for value in values if value.source.cell == cell and (sheet is None or value.source.sheet == sheet)), None)
                raw_value = match.raw_value if match else None
            elif selector_type == "header":
                header = str(rule.selector["header"]).strip()
                offset = int(rule.selector.get("row_offset", 1))
                header_value = next((value for value in values if str(value.raw_value).strip() == header), None)
                if header_value and header_value.source.row is not None:
                    target_row = header_value.source.row + offset
                    match = next((value for value in values if value.source.sheet == header_value.source.sheet and value.source.column == header_value.source.column and value.source.row == target_row), None)
                raw_value = match.raw_value if match else None
            elif selector_type == "regex":
                pattern = re.compile(rule.selector["pattern"])
                for block in blocks:
                    found = pattern.search(str(block.raw_value))
                    if found:
                        match = block
                        raw_value = found.group(int(rule.selector.get("group", 1)))
                        break
            else:
                raise ValueError(f"未知模板选择器: {selector_type}")
            if match is None:
                if rule.required:
                    raise ValueError(f"模板必填字段未找到: {rule.name}")
                continue
            extracted.append(ParsedValue(
                raw_value=raw_value,
                value_type=match.value_type,
                confidence=match.confidence,
                confidence_basis=match.confidence_basis,
                source=match.source,
                field_name=rule.name,
                target_field=rule.target_field,
            ))
        return extracted
