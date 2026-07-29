from __future__ import annotations

import hashlib
from app.engines.masking.base import RecognizerFinding


class MaskingOperator:
    """统一脱敏算子。"""

    def apply(self, text: str, findings: list[RecognizerFinding]) -> str:
        if not text or not findings:
            return text
        masked = text
        for finding in sorted(findings, key=lambda x: x.start, reverse=True):
            replacement = self._replacement_for(finding)
            masked = masked[:finding.start] + replacement + masked[finding.end:]
        return masked

    def _replacement_for(self, finding: RecognizerFinding) -> str:
        if finding.replacement is not None:
            return finding.replacement
        op = finding.operator
        raw = finding.text or ""
        if op == "remove":
            return ""
        if op == "replace":
            return f"<{finding.entity_type}>"
        if op == "hash":
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
            return f"sha256:{digest}"
        if finding.entity_type == "PHONE" and len(raw) >= 7:
            return raw[:3] + "****" + raw[-4:]
        if finding.entity_type == "TELEPHONE" and len(raw) >= 8:
            dash_idx = raw.find("-")
            if dash_idx > 0:
                return raw[:dash_idx + 1] + "****" + raw[-4:]
            if len(raw) >= 11:
                return raw[:len(raw) - 8] + "****" + raw[-4:]
            return raw[:3] + "****" + raw[-4:]
        if finding.entity_type == "ID_CARD" and len(raw) >= 10:
            return raw[:6] + "********" + raw[-4:]
        if finding.entity_type == "EMAIL" and "@" in raw:
            name, domain = raw.split("@", 1)
            return (name[:2] if len(name) >= 2 else name[:1]) + "***@" + domain
        if finding.entity_type == "NAME" and len(raw) >= 2:
            return raw[0] + "*" * (len(raw) - 1)
        return "***"
