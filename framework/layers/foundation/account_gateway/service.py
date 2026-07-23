from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any
from uuid import uuid4

from framework.core import now, standard_response
from framework.envelope import make_internal_envelope
from framework.http import post_json
from framework.module_catalog import MODULE_BY_CODE


MODULE = MODULE_BY_CODE["account-gateway"]
PBKDF2_ITERATIONS = 260_000


def get(handler: Any) -> bool:
    if handler.path == "/api/v1/capabilities":
        handler.send(200, {"items": [{"capability_code": item, "enabled": True} for item in MODULE.capabilities]})
        return True
    return False


def post(handler: Any, envelope: dict[str, Any]) -> None:
    if handler.path != MODULE.interface:
        handler.send(404, {"error": {"code": "RESOURCE_NOT_FOUND"}})
        return
    capability = envelope.get("target", {}).get("capability") or envelope.get("action")
    if capability not in MODULE.capabilities:
        handler.send(422, standard_response(envelope, "failed", error={"code": "CAPABILITY_NOT_SUPPORTED_BY_MODULE", "capability": capability}))
        return
    try:
        if capability == "account.create":
            data = _create_account(envelope)
        elif capability == "account.identity.verify":
            data = _verify_identity(envelope)
        elif capability == "account.session.resolve":
            data = _resolve_session(envelope)
        elif capability == "account.session.close":
            data = _close_session(envelope)
        elif capability == "account.identity.resolve":
            data = _resolve_identity(envelope)
        elif capability in {"account.list", "account.resource.query", "account.offboarding_assets.query"}:
            data = _query_accounts(envelope)
        elif capability in {"account.update", "account.freeze", "account.handover_confirm"}:
            data = _update_account(envelope, capability)
        elif capability == "account.delete":
            data = _delete_account(envelope)
        else:
            data = {"state": "completed", "capability": capability, "received_payload": envelope.get("payload") or {}}
    except ValueError as exc:
        handler.send(422, standard_response(envelope, "failed", error={"code": "ACCOUNT_INPUT_INVALID", "message": str(exc)}))
        return
    except RuntimeError as exc:
        handler.send(502, standard_response(envelope, "failed", error={"code": "ACCOUNT_DATA_OPERATION_FAILED", "message": str(exc)}))
        return
    handler.send(200, standard_response(envelope, "success", data=data))


def _create_account(envelope: dict[str, Any]) -> dict[str, Any]:
    payload, command = _payload_and_command(envelope)
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    password = str(payload.get("password") or account.get("password") or "")
    login_name = str(account.get("login_name") or account.get("name") or command.get("accountId") or "").strip()
    display_name = str(account.get("display_name") or account.get("displayName") or account.get("name") or login_name).strip()
    if not login_name or not display_name:
        raise ValueError("login_name and display_name are required")
    if len(password) < 6:
        raise ValueError("password must contain at least 6 characters")
    existing = _data_call(envelope, "foundation_data.query", {"dataset": "accounts", "filters": {"login_name": login_name}, "limit": 1})
    if existing.get("items"):
        raise ValueError("account login_name already exists")
    existing_display_name = _data_call(envelope, "foundation_data.query", {"dataset": "accounts", "filters": {"display_name": display_name}, "limit": 1})
    if existing_display_name.get("items"):
        raise ValueError("account display_name already exists")
    account_id = str(command.get("accountId") or account.get("account_id") or f"acc_{uuid4().hex[:16]}")
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    timestamp = now()
    role = str(account.get("role") or "普通用户")
    writes = [
        {"dataset": "accounts", "operation": "insert", "records": [{
            "account_id": account_id,
            "login_name": login_name,
            "display_name": display_name,
            "department": account.get("department"),
            "role": role,
            "status": "active",
            "owner_account_id": account_id,
            "created_at": timestamp,
        }]},
        {"dataset": "account_credentials", "operation": "insert", "records": [{
            "account_id": account_id,
            "algorithm": "pbkdf2_sha256",
            "iterations": PBKDF2_ITERATIONS,
            "salt": salt,
            "password_hash": password_hash,
            "updated_at": timestamp,
        }]},
        {"dataset": "account_role_bindings", "operation": "insert", "records": [{
            "record_id": f"{account_id}:{role}",
            "binding_id": f"binding_{uuid4().hex[:12]}",
            "account_id": account_id,
            "role_id": role,
            "scope": {"type": "tenant", "id": (envelope.get("actor") or {}).get("tenant_id") or "web-workbench"},
            "created_at": timestamp,
        }]},
    ]
    session_id = _new_session_id()
    writes.append({"dataset": "account_sessions", "operation": "insert", "records": [{
        "session_id": session_id,
        "account_id": account_id,
        "status": "active",
        "created_at": timestamp,
    }]})
    stored = _data_call(envelope, "foundation_data.write", {"writes": writes})
    return {
        "state": "created", "account_id": account_id, "login_name": login_name,
        "display_name": display_name, "role": role, "session_id": session_id, "storage": stored,
    }


def _verify_identity(envelope: dict[str, Any]) -> dict[str, Any]:
    payload, _ = _payload_and_command(envelope)
    identifier = str(payload.get("identifier") or payload.get("login_name") or payload.get("account_id") or "").strip()
    password = str(payload.get("password") or "")
    if not identifier or not password:
        raise ValueError("identifier and password are required")
    # Login names are the primary credential.  Account IDs support the seeded
    # demo accounts, while display names preserve the login behaviour promised
    # by the workbench UI for existing accounts.
    accounts = _data_call(envelope, "foundation_data.query", {"dataset": "accounts", "filters": {"login_name": identifier}, "limit": 1}).get("items") or []
    if not accounts:
        direct = _data_call(envelope, "foundation_data.read", {"dataset": "accounts", "record_id": identifier})
        if direct.get("item"):
            accounts = [direct["item"]]
    if not accounts:
        accounts = _data_call(envelope, "foundation_data.query", {"dataset": "accounts", "filters": {"display_name": identifier}, "limit": 2}).get("items") or []
        if len(accounts) > 1:
            raise ValueError("multiple accounts have this display name; use the login name or account ID")
    if not accounts:
        raise ValueError("account not found")
    account = accounts[0]
    credential = _data_call(envelope, "foundation_data.read", {"dataset": "account_credentials", "record_id": account["account_id"]}).get("item")
    if not credential or not hmac.compare_digest(_hash_password(password, credential["salt"], int(credential.get("iterations", PBKDF2_ITERATIONS))), credential["password_hash"]):
        raise ValueError("invalid account credentials")
    session_id = _new_session_id()
    _data_call(envelope, "foundation_data.write", {"dataset": "account_sessions", "operation": "insert", "records": [{
        "session_id": session_id,
        "account_id": account["account_id"],
        "status": "active",
        "created_at": now(),
    }]})
    return {"state": "verified", "account": _public_account(account), "session_id": session_id}


def _resolve_session(envelope: dict[str, Any]) -> dict[str, Any]:
    payload, _ = _payload_and_command(envelope)
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("session_id is required")
    session = _data_call(envelope, "foundation_data.read", {"dataset": "account_sessions", "record_id": session_id}).get("item")
    if not session or session.get("status") != "active":
        raise ValueError("session is not active")
    account_id = str(session.get("account_id") or "")
    account = _data_call(envelope, "foundation_data.read", {"dataset": "accounts", "record_id": account_id}).get("item")
    if not account or account.get("status") != "active":
        raise ValueError("account is not active")
    return {"state": "active", "session_id": session_id, "account": _public_account(account)}


def _close_session(envelope: dict[str, Any]) -> dict[str, Any]:
    payload, _ = _payload_and_command(envelope)
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("session_id is required")
    session = _data_call(envelope, "foundation_data.read", {"dataset": "account_sessions", "record_id": session_id}).get("item")
    if not session:
        return {"state": "not_found", "session_id": session_id}
    _data_call(envelope, "foundation_data.write", {"dataset": "account_sessions", "operation": "update", "records": [{
        "session_id": session_id,
        "status": "closed",
        "closed_at": now(),
    }]})
    return {"state": "closed", "session_id": session_id}


def _resolve_identity(envelope: dict[str, Any]) -> dict[str, Any]:
    payload, command = _payload_and_command(envelope)
    account_id = str(payload.get("account_id") or command.get("accountId") or (envelope.get("actor") or {}).get("user_id") or "")
    result = _data_call(envelope, "foundation_data.read", {"dataset": "accounts", "record_id": account_id})
    return {"state": "found" if result.get("item") else "not_found", "account": _public_account(result["item"]) if result.get("item") else None}


def _query_accounts(envelope: dict[str, Any]) -> dict[str, Any]:
    payload, _ = _payload_and_command(envelope)
    result = _data_call(envelope, "foundation_data.query", {"dataset": "accounts", "filters": payload.get("filters") or {}, "limit": payload.get("limit", 100)})
    return {"state": "completed", "items": [_public_account(item) for item in result.get("items") or []]}


def _update_account(envelope: dict[str, Any], capability: str) -> dict[str, Any]:
    payload, command = _payload_and_command(envelope)
    account_id = str(payload.get("account_id") or command.get("accountId") or "")
    if not account_id:
        raise ValueError("account_id is required")
    changes = payload.get("changes") if isinstance(payload.get("changes"), dict) else dict(payload)
    changes["account_id"] = account_id
    if capability == "account.freeze":
        changes["status"] = "frozen"
    stored = _data_call(envelope, "foundation_data.write", {"dataset": "accounts", "operation": "update", "records": [changes]})
    return {"state": "updated", "account_id": account_id, "storage": stored}


def _delete_account(envelope: dict[str, Any]) -> dict[str, Any]:
    payload, command = _payload_and_command(envelope)
    account_id = str(payload.get("account_id") or command.get("accountId") or "")
    if not account_id:
        raise ValueError("account_id is required")
    stored = _data_call(envelope, "foundation_data.write", {"dataset": "accounts", "operation": "delete", "records": [{"account_id": account_id}]})
    return {"state": "deleted", "account_id": account_id, "storage": stored}


def _data_call(envelope: dict[str, Any], capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    data_capability = {
        "foundation_data.write": "data.persist",
        "foundation_data.read": "data.read",
        "foundation_data.query": "data.search",
    }[capability]
    inner = make_internal_envelope(
        envelope.get("trace_id"),
        envelope.get("actor") or {"tenant_id": "default", "user_id": "system", "authenticated": True},
        str((envelope.get("payload") or {}).get("platform_task_id") or envelope.get("request_id")),
        data_capability,
        "business_engine",
        "engine-gateway",
        payload,
        source_layer="foundation",
        source_module="account-gateway",
    )
    status, response = post_json(
        "http://127.0.0.1:8200/api/v1/engine/instructions",
        inner,
        caller={"layer": "foundation", "module": "account-gateway"},
    )
    # The L2 engine acknowledges data operations with HTTP 202 even when its
    # synchronous storage result is already present in the response body.
    if status not in {200, 202} or response.get("status") != "success":
        raise RuntimeError(str(response))
    return ((response.get("data") or {}).get("storage_result") or {})


def _payload_and_command(envelope: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    command = payload.get("application_command") if isinstance(payload.get("application_command"), dict) else {}
    command_payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    return {**command_payload, **{key: value for key, value in payload.items() if key != "application_command"}}, command


def _hash_password(password: str, salt: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations).hex()


def _new_session_id() -> str:
    return f"sess_{uuid4().hex[:16]}"


def _public_account(account: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in account.items() if key not in {"password", "password_hash", "salt"}}
