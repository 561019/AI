from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class ScannerResult:
    scanner: str
    passed: bool
    severity: str = "low"
    risk_type: str = "none"
    evidence: str | None = None
    suggestion: str | None = None
    rule_id: str | None = None
    rule_name: str | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_hit_rule(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id or self.risk_type or self.scanner,
            "rule_name": self.rule_name or self.risk_type or self.scanner,
            "risk_level": self.severity,
            "reason": self.evidence or self.suggestion,
        }
