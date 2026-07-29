from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReferenceResolutionResult:
    resolved_text: str
    resolved_references: list[dict[str, str]]
    context_text: str | None


class ReferenceResolver:
    """Resolves explicit conversational references from caller-supplied history."""

    _OBJECTS = (
        "销售数据",
        "销售情况",
        "销售",
        "利润情况",
        "利润",
        "经营情况",
        "经营数据",
        "客户信息",
        "客户数据",
        "库存情况",
        "库存",
        "订单数据",
        "订单",
        "提成",
        "奖金",
        "费用",
        "回款",
    )

    def resolve(self, text: str, history: list[Any] | None = None) -> ReferenceResolutionResult:
        context_text = self._last_user_text(history or [])
        resolved = text.strip()
        resolutions: list[dict[str, str]] = []
        if not context_text:
            return ReferenceResolutionResult(resolved, resolutions, None)

        context_object = self._last_business_object(context_text)
        if not context_object:
            return ReferenceResolutionResult(resolved, resolutions, context_text)

        if re.fullmatch(r"(?:那|然后)?(?:继续|接着)(?:分析|看|看看|查|查询)?(?:一下)?[。！!？?]?", resolved):
            replacement = f"继续分析{context_object}"
            resolutions.append({"reference": resolved, "resolved_to": context_object})
            resolved = replacement
        else:
            for reference in ("刚才那个", "上面的", "这个", "那个"):
                if reference in resolved:
                    resolved = resolved.replace(reference, context_object)
                    resolutions.append({"reference": reference, "resolved_to": context_object})

            if re.match(r"^(?:那|然后)?再(?:分析|看|看看|查|查询)(?:一下)?$", resolved):
                resolutions.append({"reference": resolved, "resolved_to": context_object})
                resolved = f"分析{context_object}"

        return ReferenceResolutionResult(resolved, resolutions, context_text)

    def _last_user_text(self, history: list[Any]) -> str | None:
        for item in reversed(history):
            if isinstance(item, str):
                if item.strip():
                    return item.strip()
                continue

            if hasattr(item, "model_dump"):
                item = item.model_dump()
            if not isinstance(item, dict):
                continue

            role = str(item.get("role", "user"))
            if role not in {"user", "human"}:
                continue
            value = item.get("text") or item.get("content") or item.get("message")
            if value and str(value).strip():
                return str(value).strip()
        return None

    def _last_business_object(self, text: str) -> str | None:
        positions = [(text.rfind(value), value) for value in self._OBJECTS if value in text]
        positions = [item for item in positions if item[0] >= 0]
        if not positions:
            return None
        return max(positions, key=lambda item: item[0])[1]
