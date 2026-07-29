from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List
from app.engines.masking.base import RecognizerFinding


@dataclass
class RegexPattern:
    entity_type: str
    pattern: re.Pattern
    operator: str = "mask"


class RegexRecognizer:
    """个人隐私信息正则识别器。"""
    name = "regex_recognizer"

    _COMMON_SURNAMES = (
        r"王|李|张|刘|陈|杨|黄|赵|周|吴|徐|孙|马|胡|朱|郭|何|罗|高|林|"
        r"郑|梁|谢|唐|许|冯|宋|韩|邓|彭|曹|曾|田|萧|潘|袁|蔡|蒋|余|于|"
        r"杜|叶|程|魏|苏|吕|丁|董|卢|蒋|蔡|贾|丁|魏|薛|叶|阎|余|潘|戴|"
        r"夏|钟|汪|田|任|姜|范|方|石|姚|谭|廖|邹|熊|金|陆|郝|孔|白|崔|"
        r"康|毛|邱|秦|江|史|顾|侯|邵|孟|龙|万|段|雷|钱|汤|尹|易|常|武|"
        r"乔|贺|赖|龚|文"
    )
    _COMPOUND_SURNAMES = r"欧阳|司马|上官|诸葛|公孙|令狐|宇文|慕容|东方|皇甫|尉迟"

    _NAME_CONTEXT_MARKERS = [
        "叫", "姓名", "名字", "姓", "称呼", "名叫", "名为",
        "名字是", "名字叫", "姓名为", "称呼为", "称呼我", "称呼你", "称呼他", "称呼她",
    ]
    _NAME_CONNECTORS = ["是", "为", "叫", "称作", "叫做"]

    def _has_name_context(self, text: str, match_start: int) -> bool:
        if match_start == 0:
            return False
        prefix = text[:match_start]
        prefix = prefix.rstrip()
        while prefix and prefix[-1] in "：: 　、，,.\t\n\r":
            prefix = prefix[:-1]
        if any(prefix.endswith(m) for m in self._NAME_CONTEXT_MARKERS):
            return True
        for _ in range(2):
            stripped = prefix
            for conn in self._NAME_CONNECTORS:
                if stripped.endswith(conn):
                    stripped = stripped[:-len(conn)]
                    break
            if stripped == prefix:
                break
            prefix = stripped
            if any(prefix.endswith(m) for m in self._NAME_CONTEXT_MARKERS):
                return True
        return False

    def __init__(self) -> None:
        self.patterns = [
            RegexPattern("PHONE", re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")),
            RegexPattern("TELEPHONE", re.compile(r"(?<!\d)(0\d{2,3}[-]?\d{7,8})(?!\d)")),
            RegexPattern("ID_CARD", re.compile(r"(?<!\d)(\d{6}\d{8}\d{3}[0-9Xx])(?!\d)")),
            RegexPattern("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
            RegexPattern("NAME", re.compile(rf"(?:{self._COMPOUND_SURNAMES}|{self._COMMON_SURNAMES})[一-鿿]{{1,2}}")),
        ]

    def analyze(self, text: str) -> List[RecognizerFinding]:
        findings: list[RecognizerFinding] = []
        for item in self.patterns:
            for match in item.pattern.finditer(text):
                if item.entity_type == "NAME" and not self._has_name_context(text, match.start()):
                    continue
                findings.append(RecognizerFinding(
                    entity_type=item.entity_type,
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0),
                    source=self.name,
                    operator=item.operator,
                    metadata={"pattern": item.pattern.pattern},
                ))
        return findings


class BusinessKeywordRecognizer:
    name = "business_keyword_recognizer"

    def __init__(self, rules: Iterable[Dict[str, Any]]) -> None:
        self.rules = [r for r in rules if r.get("enabled", True) and r.get("rule_type") == "masking"]

    def analyze(self, text: str) -> List[RecognizerFinding]:
        findings: list[RecognizerFinding] = []
        for rule in self.rules:
            condition = rule.get("condition_json", {})
            keywords = condition.get("keywords", [])
            entity_type = condition.get("field") or rule.get("rule_id") or "BUSINESS_SECRET"
            operator = rule.get("obligation_json", {}).get("operator", "replace")
            replacement = condition.get("replacement") or rule.get("obligation_json", {}).get("replacement") or "***"
            for kw in keywords:
                if not kw:
                    continue
                start = 0
                while True:
                    idx = text.find(kw, start)
                    if idx < 0:
                        break
                    findings.append(RecognizerFinding(
                        entity_type=str(entity_type).upper(),
                        start=idx, end=idx + len(kw), text=kw,
                        source=self.name, operator=operator, replacement=replacement,
                        metadata={"rule_id": rule.get("rule_id"), "rule_name": rule.get("rule_name"), "risk_level": rule.get("risk_level", "medium")},
                    ))
                    start = idx + len(kw)
        return findings


class PresidioAdapterRecognizer:
    """Presidio 风格适配器（stub）。"""
    name = "presidio_adapter_stub"

    def analyze(self, text: str) -> List[RecognizerFinding]:
        return []
