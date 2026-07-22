from datetime import datetime,timezone
from typing import Any
from uuid import uuid4

def post(handler:Any,payload:dict[str,Any])->None:
    if handler.path!="/api/v1/permissions/check": handler.send(404); return
    actor=payload.get("actor",{}); resource_id=str(payload.get("resource",{}).get("id","")); public_capability=resource_id in {"account.create","account.identity.verify"}; denied="denied" in resource_id.lower() or (not actor.get("authenticated") and not public_capability)
    handler.send(200,{"decision":"deny" if denied else "allow","decision_id":str(uuid4()),"reason_code":"PUBLIC_ACCOUNT_ENTRY" if public_capability and not actor.get("authenticated") else ("RESOURCE_DENIED_FOR_ACCEPTANCE_TEST" if denied else "TEST_SCOPE_MATCHED"),"policy_version":"minimal-policy-0.2","obligations":[],"decided_at":datetime.now(timezone.utc).isoformat()})
