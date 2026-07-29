from dataclasses import dataclass, field
from typing import Dict, List
from app.core.enums import ModelScope
from app.engines.model_policy.policy import ModelPolicy
from app.repositories.json_store import JsonStore
from app.services.context_builder import RuntimeContext


@dataclass
class ModelBoundaryResult:
    allow_external_model: bool = True
    model_scope: ModelScope = ModelScope.EXTERNAL_ALLOWED
    need_output_check: bool = False
    allowed_model_tags: List[str] = field(default_factory=lambda: ["external", "private", "local"])
    forbidden_model_tags: List[str] = field(default_factory=list)
    hit_rules: List[Dict] = field(default_factory=list)
    model_policy: Dict = field(default_factory=dict)


class ModelBoundaryGuard:
    """模型调用边界控制 —— 简化版。"""

    def __init__(self, store: JsonStore) -> None:
        self.store = store

    def check(self, ctx: RuntimeContext, masking_hit: bool = False) -> ModelBoundaryResult:
        policy = ModelPolicy()
        hit_rules: list[dict] = []
        need_output_check = False

        text = ctx.input_text or ""
        for rule in self.store.list("security_policy_rule"):
            if not rule.get("enabled", True) or rule.get("rule_type") != "model_boundary":
                continue
            keywords = rule.get("condition_json", {}).get("keywords", [])
            if any(kw in text for kw in keywords):
                obligation = rule.get("obligation_json", {})
                scope = ModelScope(obligation.get("model_scope", "private_only"))
                policy.restrict(scope, rule.get("rule_name", rule.get("rule_id", "model_boundary")))
                need_output_check = True
                hit_rules.append({
                    "rule_id": rule["rule_id"],
                    "rule_name": rule["rule_name"],
                    "risk_level": rule.get("risk_level", "high"),
                    "reason": "命中模型边界关键词",
                })

        if masking_hit:
            need_output_check = True
            if policy.model_scope == ModelScope.EXTERNAL_ALLOWED:
                policy.reasons.append("输入/输出命中脱敏项，需进行输出复核")

        return ModelBoundaryResult(
            allow_external_model=policy.allow_external_model,
            model_scope=policy.model_scope,
            need_output_check=need_output_check,
            allowed_model_tags=policy.allowed_model_tags,
            forbidden_model_tags=policy.forbidden_model_tags,
            hit_rules=hit_rules,
            model_policy=policy.to_dict(),
        )
