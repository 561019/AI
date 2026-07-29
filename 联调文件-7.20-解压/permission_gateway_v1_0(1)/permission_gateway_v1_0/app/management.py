from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Database
from .models import (
    DataAction,
    DataDelegation,
    DataRegistry,
    Department,
    Domain,
    InstitutionPolicy,
    Person,
    PersonManagerEdge,
    PersonPositionAssignment,
    Position,
    PositionStandardPermission,
    ResourceDirectory,
    ResourcePublication,
    ResourcePublicationGrant,
    ServiceCallRule,
)
from .schemas import CommandRequest


@dataclass(frozen=True, slots=True)
class ActorContext:
    actor_id: str
    tenant_id: str
    roles: set[str]


class ManagementError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def _context(
    actor_id: str | None,
    roles: str | None,
    tenant_id: str | None,
) -> ActorContext:
    if not actor_id:
        raise ManagementError(401, "authenticated_actor_required")
    return ActorContext(
        actor_id=actor_id.strip(),
        tenant_id=(tenant_id or "").strip(),
        roles={item.strip() for item in (roles or "").split(",") if item.strip()},
    )


def _require_roles(actor: ActorContext, *roles: str) -> None:
    if not actor.roles.intersection(roles):
        raise ManagementError(403, "forbidden")


def _tenant(actor: ActorContext, payload: dict[str, Any]) -> str:
    requested = str(payload.get("tenant_id") or actor.tenant_id).strip()
    if not requested:
        raise ManagementError(400, "tenant_id_required")
    if actor.tenant_id and requested != actor.tenant_id and "breakglass" not in actor.roles:
        raise ManagementError(403, "tenant_mismatch")
    return requested


def _required(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ManagementError(400, f"{key}_required")
    return value


def _dt(value: Any, default: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return default or datetime.now(timezone.utc)


def _optional_dt(value: Any) -> datetime | None:
    return _dt(value) if value else None


def _json(value: Any, default: list[Any] | None = None) -> str:
    if value is None:
        value = default or []
    return json.dumps(value, ensure_ascii=False)


def _item(model, *, json_fields: dict[str, str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in model.__table__.columns:
        value = getattr(model, column.name)
        if isinstance(value, datetime):
            value = value.isoformat()
        result[column.name] = value
    for source, target in (json_fields or {}).items():
        raw = result.pop(source, "[]")
        try:
            result[target] = json.loads(raw)
        except (TypeError, ValueError):
            result[target] = []
    return result


def _error_response(error: ManagementError) -> JSONResponse:
    return JSONResponse(status_code=error.status, content={"error": error.code})


def create_management_router(database: Database) -> APIRouter:
    router = APIRouter()

    @router.post("/api/org/commands")
    def org_commands(
        command: CommandRequest,
        x_actor_id: str | None = Header(default=None),
        x_actor_roles: str | None = Header(default=None),
        x_tenant_id: str | None = Header(default=None),
    ):
        try:
            actor = _context(x_actor_id, x_actor_roles, x_tenant_id)
            with database.session() as session:
                result = _execute_org_command(session, actor, command)
                session.commit()
                return JSONResponse(status_code=_command_status(command.action), content=result)
        except ManagementError as error:
            return _error_response(error)
        except IntegrityError:
            return JSONResponse(status_code=409, content={"error": "conflict"})

    @router.get("/api/org/snapshot")
    def org_snapshot(
        tenant_id: str | None = Query(default=None),
        manager_person_id: str | None = Query(default=None),
        domain_id: str | None = Query(default=None),
        x_actor_id: str | None = Header(default=None),
        x_actor_roles: str | None = Header(default=None),
        x_tenant_id: str | None = Header(default=None),
    ):
        try:
            actor = _context(x_actor_id, x_actor_roles, x_tenant_id)
            _require_roles(actor, "hanhe_im", "hanhe_dsm", "hanhe_admin", "breakglass")
            scoped = _tenant(actor, {"tenant_id": tenant_id})
            with database.session() as session:
                people = session.scalars(select(Person).where(Person.tenant_id == scoped)).all()
                departments = session.scalars(
                    select(Department).where(Department.tenant_id == scoped)
                ).all()
                positions = session.scalars(
                    select(Position).where(Position.tenant_id == scoped)
                ).all()
                assignments = session.scalars(
                    select(PersonPositionAssignment).where(
                        PersonPositionAssignment.tenant_id == scoped
                    )
                ).all()
                domains = session.scalars(select(Domain).where(Domain.tenant_id == scoped)).all()
                edge_query = select(PersonManagerEdge).where(
                    PersonManagerEdge.tenant_id == scoped
                )
                if domain_id:
                    edge_query = edge_query.where(PersonManagerEdge.domain_id == domain_id)
                edges = (
                    session.scalars(edge_query).all()
                    if actor.roles.intersection({"hanhe_dsm", "hanhe_admin", "breakglass"})
                    else []
                )
                subordinates = _subordinates(edges, manager_person_id) if manager_person_id else []
                return {
                    "persons": [_item(item) for item in people],
                    "departments": [_item(item) for item in departments],
                    "positions": [
                        _item(item, json_fields={"tags_json": "tags"}) for item in positions
                    ],
                    "assignments": [_item(item) for item in assignments],
                    "domains": [_item(item) for item in domains],
                    "manager_edges": [_item(item) for item in edges],
                    "subordinates": subordinates,
                }
        except ManagementError as error:
            return _error_response(error)

    @router.post("/api/permissions/commands")
    def permission_commands(
        command: CommandRequest,
        x_actor_id: str | None = Header(default=None),
        x_actor_roles: str | None = Header(default=None),
        x_tenant_id: str | None = Header(default=None),
    ):
        try:
            actor = _context(x_actor_id, x_actor_roles, x_tenant_id)
            with database.session() as session:
                result = _execute_permission_command(session, actor, command)
                session.commit()
                return JSONResponse(status_code=_command_status(command.action), content=result)
        except ManagementError as error:
            return _error_response(error)
        except IntegrityError:
            return JSONResponse(status_code=409, content={"error": "conflict"})

    @router.get("/api/permissions/snapshot")
    def permission_snapshot(
        tenant_id: str | None = Query(default=None),
        resource_id: str | None = Query(default=None),
        person_id: str | None = Query(default=None),
        x_actor_id: str | None = Header(default=None),
        x_actor_roles: str | None = Header(default=None),
        x_tenant_id: str | None = Header(default=None),
    ):
        try:
            actor = _context(x_actor_id, x_actor_roles, x_tenant_id)
            _require_roles(actor, "hanhe_dsm", "hanhe_admin", "breakglass")
            scoped = _tenant(actor, {"tenant_id": tenant_id})
            with database.session() as session:
                standards = session.scalars(
                    select(PositionStandardPermission).where(
                        PositionStandardPermission.tenant_id == scoped
                    )
                ).all()
                delegation_query = select(DataDelegation).where(
                    DataDelegation.tenant_id == scoped
                )
                if resource_id:
                    delegation_query = delegation_query.where(
                        DataDelegation.resource_id == resource_id
                    )
                if person_id:
                    delegation_query = delegation_query.where(
                        (DataDelegation.from_person_id == person_id)
                        | (DataDelegation.to_person_id == person_id)
                    )
                delegations = session.scalars(delegation_query).all()
                data_query = select(DataRegistry).where(DataRegistry.tenant_id == scoped)
                if resource_id:
                    data_query = data_query.where(DataRegistry.id == resource_id)
                records = session.scalars(data_query).all()
                resources = session.scalars(
                    select(ResourceDirectory).where(ResourceDirectory.tenant_id == scoped)
                ).all()
                resource_ids = [item.id for item in resources]
                publications = (
                    session.scalars(
                        select(ResourcePublication).where(
                            ResourcePublication.resource_id.in_(resource_ids)
                        )
                    ).all()
                    if resource_ids
                    else []
                )
                actions = session.scalars(select(DataAction).order_by(DataAction.action)).all()
                policies = session.scalars(
                    select(InstitutionPolicy).where(InstitutionPolicy.tenant_id == scoped)
                ).all()
                service_rules = session.scalars(select(ServiceCallRule)).all()
                return {
                    "position_standard_resources": [
                        _item(
                            item,
                            json_fields={"data_states_json": "data_states"},
                        )
                        for item in standards
                    ],
                    "delegations": [
                        _item(item, json_fields={"data_states_json": "data_states"})
                        for item in delegations
                    ],
                    "resources": [_item(item) for item in resources],
                    "data_actions": [_item(item) for item in actions],
                    "data_records": [
                        _item(
                            item,
                            json_fields={
                                "allowed_actions_json": "allowed_actions",
                                "initial_person_ids_json": "initial_person_ids",
                                "business_tags_json": "business_tags",
                                "storage_refs_json": "storage_refs",
                            },
                        )
                        for item in records
                    ],
                    "data_access_summary": _data_access_summary(records, standards, delegations),
                    "institution_policies": [
                        _item(item, json_fields={"data_states_json": "data_states"})
                        for item in policies
                    ],
                    "service_call_rules": [_item(item) for item in service_rules],
                    "resource_publications": [_item(item) for item in publications],
                }
        except ManagementError as error:
            return _error_response(error)

    return router


def _command_status(action: str) -> int:
    if action in {
        "end_person_position",
        "set_data_status",
        "approve_resource_publication",
        "revoke_resource_publication",
    }:
        return 200
    return 201


def _execute_org_command(
    session: Session, actor: ActorContext, command: CommandRequest
) -> dict[str, Any]:
    payload = command.payload
    now = datetime.now(timezone.utc)
    if command.action == "upsert_person":
        _require_roles(actor, "hanhe_im", "hanhe_admin")
        tenant_id = _tenant(actor, payload)
        actor_id = _required(payload, "actor_id")
        person_id = str(payload.get("id") or actor_id).strip()
        if person_id != actor_id:
            raise ManagementError(400, "account_person_mismatch")
        item = session.get(Person, person_id)
        if item is None:
            item = Person(
                id=person_id,
                actor_id=actor_id,
                tenant_id=tenant_id,
                display_name=str(payload.get("display_name", "")),
                status=str(payload.get("status", "active")),
                created_at=now,
            )
            session.add(item)
        else:
            item.actor_id = actor_id
            item.display_name = str(payload.get("display_name", item.display_name))
            item.status = str(payload.get("status", item.status))
        session.flush()
        return {"action": command.action, "person": _item(item)}
    if command.action == "create_department":
        _require_roles(actor, "hanhe_im", "hanhe_admin")
        item = Department(
            id=_required(payload, "id"),
            tenant_id=_tenant(actor, payload),
            name=_required(payload, "name"),
            parent_id=str(payload.get("parent_id") or "") or None,
            status=str(payload.get("status", "active")),
            created_at=now,
        )
        session.add(item)
        session.flush()
        return {"action": command.action, "department": _item(item)}
    if command.action == "create_position":
        _require_roles(actor, "hanhe_im", "hanhe_admin")
        item = Position(
            id=_required(payload, "id"),
            title=_required(payload, "title"),
            department_id=str(payload.get("department_id", "")),
            tenant_id=_tenant(actor, payload),
            tags_json=_json(payload.get("tags", [])),
            status=str(payload.get("status", "active")),
            created_by=actor.actor_id,
            created_at=now,
        )
        session.add(item)
        session.flush()
        return {
            "action": command.action,
            "position": _item(item, json_fields={"tags_json": "tags"}),
        }
    if command.action == "assign_person_position":
        _require_roles(actor, "hanhe_im", "hanhe_admin")
        tenant_id = _tenant(actor, payload)
        actor_id = str(payload.get("actor_id") or payload.get("user_id") or "").strip()
        if not actor_id:
            raise ManagementError(400, "actor_id_required")
        person_id = str(payload.get("person_id") or actor_id).strip()
        if person_id != actor_id:
            raise ManagementError(400, "account_person_mismatch")
        person = session.get(Person, person_id)
        if person is None:
            person = Person(
                id=person_id,
                actor_id=actor_id,
                tenant_id=tenant_id,
                display_name="",
                status="active",
                created_at=now,
            )
            session.add(person)
        item = PersonPositionAssignment(
            person_id=person_id,
            actor_id=actor_id,
            position_id=_required(payload, "position_id"),
            tenant_id=tenant_id,
            status="active",
            effective_from=_dt(payload.get("effective_from") or payload.get("assigned_at"), now),
            effective_to=_optional_dt(payload.get("effective_to")),
            assigned_by=actor.actor_id,
        )
        session.add(item)
        session.flush()
        return {"action": command.action, "assignment": _item(item)}
    if command.action == "end_person_position":
        _require_roles(actor, "hanhe_im", "hanhe_admin")
        item = session.get(PersonPositionAssignment, int(payload.get("id", 0)))
        if item is None:
            raise ManagementError(404, "assignment_not_found")
        _tenant(actor, {"tenant_id": item.tenant_id})
        item.status = "ended"
        item.effective_to = now
        item.ended_by = actor.actor_id
        session.flush()
        return {"action": command.action, "assignment": _item(item)}
    if command.action == "create_domain":
        _require_roles(actor, "hanhe_admin")
        item = Domain(
            id=_required(payload, "id"),
            name=_required(payload, "name"),
            tenant_id=_tenant(actor, payload),
            dsm_actor_id=str(payload.get("dsm_user_id") or payload.get("dsm_actor_id") or ""),
            created_by=actor.actor_id,
            created_at=now,
        )
        session.add(item)
        session.flush()
        return {"action": command.action, "domain": _item(item)}
    if command.action == "upsert_manager_edge":
        _require_roles(actor, "hanhe_dsm", "hanhe_admin")
        tenant_id = _tenant(actor, payload)
        person_id = _required(payload, "person_id")
        manager_id = _required(payload, "manager_person_id")
        domain_id = _required(payload, "domain_id")
        if session.get(Person, person_id) is None or session.get(Person, manager_id) is None:
            raise ManagementError(404, "account_not_found")
        if person_id == manager_id:
            raise ManagementError(409, "manager_cycle")
        _ensure_no_manager_cycle(session, tenant_id, domain_id, person_id, manager_id)
        current = session.scalar(
            select(PersonManagerEdge).where(
                PersonManagerEdge.tenant_id == tenant_id,
                PersonManagerEdge.domain_id == domain_id,
                PersonManagerEdge.person_id == person_id,
                PersonManagerEdge.status == "active",
            )
        )
        if current is not None:
            current.status = "ended"
            current.effective_to = now
            session.flush()
        item = PersonManagerEdge(
            person_id=person_id,
            manager_person_id=manager_id,
            domain_id=domain_id,
            tenant_id=tenant_id,
            status="active",
            effective_from=now,
            created_by=actor.actor_id,
        )
        session.add(item)
        session.flush()
        return {"action": command.action, "manager_edge": _item(item)}
    raise ManagementError(400, "unknown_action")


def _execute_permission_command(
    session: Session, actor: ActorContext, command: CommandRequest
) -> dict[str, Any]:
    _require_roles(actor, "hanhe_dsm", "hanhe_admin")
    payload = command.payload
    tenant_id = _tenant(actor, payload)
    now = datetime.now(timezone.utc)
    if command.action == "create_position_standard_resource":
        item = PositionStandardPermission(
            tenant_id=tenant_id,
            position_id=_required(payload, "position_id"),
            action=_required(payload, "action"),
            data_label=str(payload.get("data_label", "*")),
            data_states_json=_json(payload.get("data_states", ["active"])),
            source_service=str(payload.get("source_service", "*")),
            target_service=str(payload.get("target_service", "*")),
            resource_type=str(payload.get("resource_type", "*")),
            resource_id=str(payload.get("resource_id", "*")),
            effect=str(payload.get("effect", "allow")),
            valid_from=_dt(payload.get("valid_from"), now),
            valid_to=_optional_dt(payload.get("valid_to")),
            basis=str(payload.get("basis", "岗位标准配置")),
            created_by=actor.actor_id,
        )
        session.add(item)
        session.flush()
        return {
            "action": command.action,
            "position_standard_resource": _item(
                item, json_fields={"data_states_json": "data_states"}
            ),
        }
    if command.action == "create_delegation":
        from_account_id = _required(payload, "from_person_id")
        to_account_id = _required(payload, "to_person_id")
        # Account existence and employment are identity facts owned by the
        # account gateway. This module stores only the grant; the L1 identity
        # context proves the current recipient at decision time.
        item = DataDelegation(
            tenant_id=tenant_id,
            from_person_id=from_account_id,
            to_person_id=to_account_id,
            resource_type=str(payload.get("resource_type", "data")),
            resource_id=_required(payload, "resource_id"),
            action=_required(payload, "action"),
            data_label=str(payload.get("data_label", "*")),
            data_states_json=_json(payload.get("data_states", ["active"])),
            can_redelegate=bool(payload.get("can_redelegate", False)),
            valid_from=_dt(payload.get("valid_from"), now),
            valid_to=_optional_dt(payload.get("valid_to")),
            basis=_required(payload, "basis"),
            created_by=actor.actor_id,
        )
        session.add(item)
        session.flush()
        return {
            "action": command.action,
            "delegation": _item(item, json_fields={"data_states_json": "data_states"}),
        }
    if command.action in {"register_data", "register_data_record"}:
        owner_account_id = str(
            payload.get("owner_actor_id") or payload.get("owner_user_id") or ""
        ).strip()
        owner_person_id = str(payload.get("owner_person_id") or owner_account_id).strip()
        if not owner_account_id:
            raise ManagementError(400, "owner_account_id_required")
        if owner_person_id != owner_account_id:
            raise ManagementError(400, "account_person_mismatch")
        item = DataRegistry(
            id=_required(payload, "id"),
            tenant_id=tenant_id,
            title=_required(payload, "title"),
            source_type=_required(payload, "source_type"),
            owner_person_id=owner_account_id,
            owner_actor_id=owner_account_id,
            data_label=str(payload.get("data_label", "normal")),
            state=str(payload.get("state") or payload.get("status") or "active"),
            allowed_actions_json=_json(payload.get("allowed_actions", [])),
            initial_person_ids_json=_json(payload.get("initial_person_ids", [])),
            business_tags_json=_json(payload.get("business_tags", [])),
            storage_refs_json=_json(payload.get("storage_refs", [])),
            basis=_required(payload, "basis"),
            created_by=actor.actor_id,
            created_at=now,
            updated_at=now,
        )
        session.add(item)
        session.flush()
        return {"action": command.action, "data_record": _item(item)}
    if command.action == "register_data_action":
        action_name = _required(payload, "action")
        item = session.get(DataAction, action_name)
        if item is None:
            item = DataAction(
                action=action_name,
                description=_required(payload, "description"),
                risk_level=str(payload.get("risk_level", "normal")),
                enabled=bool(payload.get("enabled", True)),
                created_by=actor.actor_id,
                created_at=now,
            )
            session.add(item)
        else:
            item.description = str(payload.get("description", item.description))
            item.risk_level = str(payload.get("risk_level", item.risk_level))
            item.enabled = bool(payload.get("enabled", item.enabled))
        session.flush()
        return {"action": command.action, "data_action": _item(item)}
    if command.action == "set_data_status":
        item = session.get(DataRegistry, _required(payload, "id"))
        if item is None:
            raise ManagementError(404, "data_record_not_found")
        item.state = str(payload.get("state") or payload.get("status") or "")
        if not item.state:
            raise ManagementError(400, "status_required")
        item.updated_at = now
        session.flush()
        return {"action": command.action, "data_record": _item(item)}
    if command.action == "create_institution_policy":
        effect = str(payload.get("effect", "deny"))
        if effect not in {"allow", "deny"}:
            raise ManagementError(400, "invalid_effect")
        item = InstitutionPolicy(
            tenant_id=tenant_id,
            name=_required(payload, "name"),
            subject_type=str(payload.get("subject_type", "any")),
            subject_id=str(payload.get("subject_id", "*")),
            action=str(payload.get("action", "*")),
            data_label=str(payload.get("data_label", "*")),
            data_states_json=_json(payload.get("data_states", ["*"])),
            source_service=str(payload.get("source_service", "*")),
            target_service=str(payload.get("target_service", "*")),
            resource_type=str(payload.get("resource_type", "*")),
            resource_id=str(payload.get("resource_id", "*")),
            effect=effect,
            priority=int(payload.get("priority", 100)),
            valid_from=_dt(payload.get("valid_from"), now),
            valid_to=_optional_dt(payload.get("valid_to")),
            basis=_required(payload, "basis"),
            created_by=actor.actor_id,
        )
        session.add(item)
        session.flush()
        return {"action": command.action, "institution_policy": _item(item)}
    if command.action == "create_service_call_rule":
        item = ServiceCallRule(
            source_service=_required(payload, "source_service"),
            target_service=_required(payload, "target_service"),
            action=str(payload.get("action", "*")),
            enabled=bool(payload.get("enabled", True)),
            created_by=actor.actor_id,
            created_at=now,
        )
        session.add(item)
        session.flush()
        return {"action": command.action, "service_call_rule": _item(item)}
    if command.action == "create_resource":
        owner_account_id = str(
            payload.get("owner_actor_id") or payload.get("owner_user_id") or ""
        ).strip()
        owner_person_id = str(payload.get("owner_person_id") or owner_account_id).strip()
        if not owner_account_id:
            raise ManagementError(400, "owner_account_id_required")
        if owner_person_id != owner_account_id:
            raise ManagementError(400, "account_person_mismatch")
        item = ResourceDirectory(
            id=_required(payload, "id"),
            name=_required(payload, "name"),
            resource_type=_required(payload, "resource_type"),
            level=str(payload.get("level", "personal_position")),
            status=str(payload.get("status", "active")),
            owner_person_id=owner_account_id,
            owner_actor_id=owner_account_id,
            owner_position_id=_required(payload, "owner_position_id"),
            department_id=str(payload.get("department_id", "")),
            tenant_id=tenant_id,
            created_by=actor.actor_id,
            created_at=now,
        )
        session.add(item)
        session.flush()
        return {"action": command.action, "resource": _item(item)}
    if command.action == "request_resource_publication":
        item = ResourcePublication(
            resource_id=_required(payload, "resource_id"),
            target_level=_required(payload, "target_level"),
            reason=_required(payload, "reason"),
            status="pending",
            requested_by=actor.actor_id,
            requested_at=now,
        )
        session.add(item)
        session.flush()
        return {"action": command.action, "resource_publication": _item(item)}
    if command.action == "approve_resource_publication":
        item = session.get(ResourcePublication, int(payload.get("id", 0)))
        if item is None:
            raise ManagementError(404, "resource_publication_not_found")
        resource = session.get(ResourceDirectory, item.resource_id)
        if resource is None or resource.tenant_id != tenant_id:
            raise ManagementError(404, "resource_not_found")
        position_ids = payload.get("position_ids")
        actions = payload.get("actions", ["use"])
        if not isinstance(position_ids, list) or not position_ids or not all(isinstance(value, str) and value.strip() for value in position_ids):
            raise ManagementError(400, "publication_position_ids_required")
        if not isinstance(actions, list) or not actions or not all(isinstance(value, str) and value.strip() for value in actions):
            raise ManagementError(400, "publication_actions_required")
        valid_to = _optional_dt(payload.get("valid_to"))
        grant_ids: list[int] = []
        for position_id in sorted(set(position_ids)):
            for action in sorted(set(actions)):
                permission = PositionStandardPermission(
                    tenant_id=tenant_id,
                    position_id=position_id,
                    action=action,
                    data_label=str(payload.get("data_label", "normal")),
                    data_states_json=_json(payload.get("data_states", ["active"])),
                    source_service=str(payload.get("source_service", "*")),
                    target_service=str(payload.get("target_service", "*")),
                    resource_type=resource.resource_type,
                    resource_id=resource.id,
                    effect="allow",
                    valid_from=now,
                    valid_to=valid_to,
                    basis=f"资源发布审批:{item.id}:{item.reason}",
                    created_by=actor.actor_id,
                )
                session.add(permission)
                session.flush()
                session.add(ResourcePublicationGrant(publication_id=item.id, position_permission_id=permission.id, created_at=now))
                grant_ids.append(permission.id)
        item.status = "approved"
        item.approved_by = actor.actor_id
        item.approved_at = now
        resource.level = item.target_level
        session.flush()
        return {"action": command.action, "resource_publication": _item(item), "position_permission_ids": grant_ids}
    if command.action == "revoke_resource_publication":
        item = session.get(ResourcePublication, int(payload.get("id", 0)))
        if item is None:
            raise ManagementError(404, "resource_publication_not_found")
        resource = session.get(ResourceDirectory, item.resource_id)
        if resource is None or resource.tenant_id != tenant_id:
            raise ManagementError(404, "resource_not_found")
        if item.status != "approved":
            raise ManagementError(409, "resource_publication_not_approved")
        grants = session.scalars(
            select(ResourcePublicationGrant).where(
                ResourcePublicationGrant.publication_id == item.id
            )
        ).all()
        revoked_ids = [grant.position_permission_id for grant in grants]
        permissions = [session.get(PositionStandardPermission, grant.position_permission_id) for grant in grants]
        for grant in grants:
            session.delete(grant)
        # Flush association deletes before removing their referenced grants.
        session.flush()
        for permission in permissions:
            if permission is not None:
                session.delete(permission)
        item.status = "revoked"
        item.approved_by = actor.actor_id
        item.approved_at = now
        session.flush()
        return {"action": command.action, "resource_publication": _item(item), "revoked_position_permission_ids": revoked_ids}
    raise ManagementError(400, "unknown_action")


def _ensure_no_manager_cycle(
    session: Session,
    tenant_id: str,
    domain_id: str,
    person_id: str,
    manager_id: str,
) -> None:
    edges = session.scalars(
        select(PersonManagerEdge).where(
            PersonManagerEdge.tenant_id == tenant_id,
            PersonManagerEdge.domain_id == domain_id,
            PersonManagerEdge.status == "active",
        )
    ).all()
    manager_of = {item.person_id: item.manager_person_id for item in edges if item.person_id != person_id}
    current = manager_id
    seen: set[str] = set()
    while current:
        if current == person_id:
            raise ManagementError(409, "manager_cycle")
        if current in seen:
            raise ManagementError(409, "manager_cycle")
        seen.add(current)
        current = manager_of.get(current, "")


def _subordinates(edges: list[PersonManagerEdge], manager_person_id: str) -> list[dict[str, Any]]:
    children: dict[str, list[str]] = {}
    domain_by_pair: dict[tuple[str, str], str] = {}
    for edge in edges:
        if edge.status != "active":
            continue
        children.setdefault(edge.manager_person_id, []).append(edge.person_id)
        domain_by_pair[(edge.manager_person_id, edge.person_id)] = edge.domain_id
    result: list[dict[str, Any]] = []
    pending = [(item, manager_person_id, 1) for item in children.get(manager_person_id, [])]
    seen: set[str] = set()
    while pending:
        person_id, manager_id, depth = pending.pop(0)
        if person_id in seen:
            continue
        seen.add(person_id)
        result.append(
            {
                "person_id": person_id,
                "manager_person_id": manager_id,
                "domain_id": domain_by_pair.get((manager_id, person_id), ""),
                "depth": depth,
            }
        )
        pending.extend((item, person_id, depth + 1) for item in children.get(person_id, []))
    return result


def _data_access_summary(
    records: list[DataRegistry],
    standards: list[PositionStandardPermission],
    delegations: list[DataDelegation],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in records:
        for action in json.loads(record.allowed_actions_json or "[]"):
            result.append(
                {
                    "data_id": record.id,
                    "source": "owner",
                    "person_id": record.owner_person_id,
                    "action": action,
                    "policy_id": f"data_owner:{record.id}:{action}",
                }
            )
        for person_id in json.loads(record.initial_person_ids_json or "[]"):
            for action in {"read", "fetch", "use"}.intersection(
                json.loads(record.allowed_actions_json or "[]")
            ):
                result.append(
                    {
                        "data_id": record.id,
                        "source": "initial_participant",
                        "person_id": person_id,
                        "action": action,
                        "policy_id": f"data_initial:{record.id}:{person_id}:{action}",
                    }
                )
    for item in standards:
        if item.resource_type == "data" and item.resource_id != "*":
            result.append(
                {
                    "data_id": item.resource_id,
                    "source": "position_standard",
                    "position_id": item.position_id,
                    "action": item.action,
                    "policy_id": f"position_standard:{item.id}",
                }
            )
    for item in delegations:
        result.append(
            {
                "data_id": item.resource_id,
                "source": "delegation",
                "person_id": item.to_person_id,
                "action": item.action,
                "policy_id": f"delegation:{item.id}",
            }
        )
    return result
