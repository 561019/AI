from dataclasses import dataclass
from typing import Any, Dict, Optional
from app.repositories.json_store import JsonStore
from app.schemas.security import SecurityCheckRequest


@dataclass
class RuntimeContext:
    input_text: str
    real_person_id: str
    is_emergency_account: bool
    domain_id: Optional[str] = None


class RuntimeContextBuilder:
    """简化版上下文构建器 —— 仅用于 check 流程。"""

    def __init__(self, store: JsonStore) -> None:
        self.store = store

    def build_from_check(self, req: SecurityCheckRequest, account_id: str) -> RuntimeContext:
        # 通过 real_person_id 查找真实 account_id
        records = self.store.find("accounts", person_id=req.real_person_id)
        if records:
            resolved_account_id = records[0].get("account_id", account_id)
        else:
            resolved_account_id = account_id

        return RuntimeContext(
            input_text=req.input_text,
            real_person_id=req.real_person_id,
            is_emergency_account=req.is_emergency or False,
            domain_id=None,
        )
