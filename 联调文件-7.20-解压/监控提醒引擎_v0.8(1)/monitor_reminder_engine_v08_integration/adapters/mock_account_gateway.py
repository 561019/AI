from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from adapters.adapter_registry import record_adapter_call


ROLE_DIRECTORY: dict[str, dict[str, str]] = {
    "采购经办岗位": {
        "person_id": "person_zhangsan",
        "display_name": "张三",
    },
    "采购负责人岗位": {
        "person_id": "person_lisi",
        "display_name": "李四",
    },
    "总经办岗位": {
        "person_id": "person_wangwu",
        "display_name": "王五",
    },
    "财务负责人岗位": {
        "person_id": "person_zhaoliu",
        "display_name": "赵六",
    },
    "投诉办理岗位": {
        "person_id": "person_sunqi",
        "display_name": "孙七",
    },
    "投诉负责人岗位": {
        "person_id": "person_zhouba",
        "display_name": "周八",
    },
    "合规负责人岗位": {
        "person_id": "person_wujiu",
        "display_name": "吴九",
    },
}


def resolve_current_holder(
    receiver_role: str,
    *,
    tenant_id: str = "tenant_hanhe",
) -> dict[str, Any]:
    resolution_id = f"acct_res_{uuid4().hex}"
    person = ROLE_DIRECTORY.get(receiver_role)
    result: dict[str, Any] = {
        "resolution_id": resolution_id,
        "receiver_role": receiver_role,
        "tenant_id": tenant_id,
        "resolved_at": datetime.now().isoformat(timespec="seconds"),
        "found": person is not None,
    }

    if person:
        result.update(person)
        result["employment_status"] = "active"
        result["receive_qualified"] = True
    else:
        result.update(
            {
                "person_id": "",
                "display_name": "",
                "employment_status": "unknown",
                "receive_qualified": False,
            }
        )

    record_adapter_call(
        "account_gateway_1_8",
        "account.resolve_role_holder",
        result,
    )
    return result
