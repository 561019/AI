from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class RecognizerFinding:
    entity_type: str
    start: int
    end: int
    text: str
    score: float = 1.0
    source: str = "unknown"
    operator: str = "mask"
    replacement: str | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "start": self.start,
            "end": self.end,
            "text_preview": self.text[:3] + "***" if self.text else "",
            "score": self.score,
            "source": self.source,
            "operator": self.operator,
            "replacement": self.replacement,
            "metadata": self.metadata,
        }
