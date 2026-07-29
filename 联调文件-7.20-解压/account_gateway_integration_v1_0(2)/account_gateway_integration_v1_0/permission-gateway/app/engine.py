from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .models import (
    DataAction,
    DataDelegation,
    DataRegistry,
    InstitutionPolicy,
    Person,
    PersonManagerEdge,
    PersonPositionAssignment,
    PositionStandardPermission,
    ServiceCallRule,
)
from .schemas import PermissionCheckRequest


@dataclass(frozen=True, slots=True)
class EngineDecision:
    allowed: bool
    reason_code: str
    reason: str
    policy_id: str | None = None
    person_id: str | None = None
    position_id: str | None = None


REASONS = {
    "PERMISSION_GRANTED": "当前人员拥有本次操作权限",
    "USER_NOT_FOUND": "找不到用户账号",
    "PERSON_NOT_FOUND": "找不到对应真人",
    "NO_ACTIVE_POSITION": "当前真人没有有效任职岗位",
    "ACTION_NOT_GRANTED": "当前人员没有该动作权限",
    "DATA_LABEL_DENIED": "当前人员无权访问该数据标签",
    "DATA_STATE_DENIED": "当前数据状态禁止该操作",
    "PERMISSION_EXPIRED": "匹配的权限已经过期",
    "SERVICE_CALL_DENIED": "当前服务调用关系不允许",
}


def _decision(
    allowed: bool,
    code: str,
    *,
    policy_id: str | None = None,
    person_id: str | None = None,
    position_id: str | None = None,
) -> EngineDecision:
    return EngineDecision(
        allowed=allowed,
        reason_code=code,
        reason=REASONS[code],
        policy_id=policy_id,
        person_id=person_id,
        position_id=position_id,
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _active(valid_from: datetime, valid_to: datetime | None, now: datetime) -> bool:
    start = _utc(valid_from)
    end = _utc(valid_to)
    return bool(start and start <= now and (end is None or end > now))


def _json_list(raw: str, default: list[str] | None = None) -> list[str]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return default or []
    return [str(item) for item in value] if isinstance(value, list) else (default or [])


def _matches(pattern: str | None, value: str | None) -> bool:
    pattern = pattern or "*"
    value = value or ""
    return pattern == "*" or pattern == value


def _matches_common(rule, request: PermissionCheckRequest) -> bool:
    return (
        _matches(rule.action, request.action)
        and _matches(rule.data_label, request.data_label)
        and _matches(rule.source_service, request.source_service)
        and _matches(rule.target_service, request.target_service)
        and _matches(rule.resource_type, request.resource_type)
        and _matches(rule.resource_id, request.resource_id)
        and ("*" in _json_list(rule.data_states_json) or request.data_state in _json_list(rule.data_states_json))
    )


class PermissionEngine:
    def evaluate(
        self,
        session: Session,
        request: PermissionCheckRequest,
        *,
        now: datetime | None = None,
    ) -> EngineDecision:
        now = _utc(now or datetime.now(timezone.utc))
        assert now is not None

        if not self._service_call_allowed(session, request):
            return _decision(False, "SERVICE_CALL_DENIED")

        action = session.get(DataAction, request.action)
        if action is None or not action.enabled:
            return _decision(False, "ACTION_NOT_GRANTED")

        data_record = self._data_record(session, request)
        constraint = self._data_constraint(request, data_record)
        if constraint is not None:
            return constraint

        # Formal L1 traffic brings account-gateway-verified identity facts.  The
        # permission database must not become a second organization authority.
        if request.identity_position_ids:
            person = Person(id=request.actor_id, actor_id=request.actor_id, tenant_id=request.tenant_id or "", display_name="", status="active")
            position_ids = set(request.identity_position_ids)
            active_position_id = next(iter(position_ids))
        else:
            person, person_error = self._resolve_person(session, request)
            if person_error is not None:
                return person_error
            assert person is not None
            assignments = self._active_assignments(session, request, person.id, now)
            if not assignments:
                return _decision(False, "NO_ACTIVE_POSITION", person_id=person.id)
            position_ids = {item.position_id for item in assignments}
            active_position_id = assignments[0].position_id

        deny = self._institution_decision(
            session, request, person, position_ids, now, effect="deny"
        )
        if deny is not None:
            return _decision(
                False,
                "ACTION_NOT_GRANTED",
                policy_id=f"institution_policy:{deny.id}",
                person_id=person.id,
                position_id=active_position_id,
            )

        data_allow = self._registered_data_allow(data_record, request, person.id)
        if data_allow is not None:
            return _decision(
                True,
                "PERMISSION_GRANTED",
                policy_id=data_allow,
                person_id=person.id,
                position_id=active_position_id,
            )

        standard = self._position_standard_allow(
            session, request, position_ids, now
        )
        if standard is not None:
            return _decision(
                True,
                "PERMISSION_GRANTED",
                policy_id=f"position_standard:{standard.id}",
                person_id=person.id,
                position_id=standard.position_id,
            )

        manager_scope_allowed = (
            data_record is not None
            and (
                data_record.owner_person_id in request.identity_managed_person_ids
                if request.identity_position_ids
                else self._manager_scope_allow(
                    session, request, person.id, data_record.owner_person_id
                )
            )
        )
        if manager_scope_allowed:
            return _decision(
                True,
                "PERMISSION_GRANTED",
                policy_id=(
                    f"manager_scope:{request.domain_id or '*'}:{person.id}:"
                    f"{data_record.owner_person_id}"
                ),
                person_id=person.id,
                position_id=active_position_id,
            )

        delegation = self._delegation_allow(session, request, person.id, now)
        if delegation is not None:
            return _decision(
                True,
                "PERMISSION_GRANTED",
                policy_id=f"delegation:{delegation.id}",
                person_id=person.id,
                position_id=active_position_id,
            )

        policy = self._institution_decision(
            session, request, person, position_ids, now, effect="allow"
        )
        if policy is not None:
            return _decision(
                True,
                "PERMISSION_GRANTED",
                policy_id=f"institution_policy:{policy.id}",
                person_id=person.id,
                position_id=active_position_id,
            )

        if self._has_expired_match(session, request, person, position_ids, now):
            return _decision(
                False,
                "PERMISSION_EXPIRED",
                person_id=person.id,
                position_id=active_position_id,
            )

        if self._has_action_match_for_other_label(session, request, position_ids):
            return _decision(
                False,
                "DATA_LABEL_DENIED",
                person_id=person.id,
                position_id=active_position_id,
            )
        return _decision(
            False,
            "ACTION_NOT_GRANTED",
            person_id=person.id,
            position_id=active_position_id,
        )

    @staticmethod
    def _service_call_allowed(session: Session, request: PermissionCheckRequest) -> bool:
        rule = session.scalar(
            select(ServiceCallRule.id).where(
                ServiceCallRule.enabled.is_(True),
                or_(
                    ServiceCallRule.source_service == request.source_service,
                    ServiceCallRule.source_service == "*",
                ),
                or_(
                    ServiceCallRule.target_service == request.target_service,
                    ServiceCallRule.target_service == "*",
                ),
                or_(ServiceCallRule.action == request.action, ServiceCallRule.action == "*"),
            )
        )
        return rule is not None

    @staticmethod
    def _data_record(
        session: Session, request: PermissionCheckRequest
    ) -> DataRegistry | None:
        if not request.resource_id:
            return None
        record = session.get(DataRegistry, request.resource_id)
        if record is None:
            return None
        if request.tenant_id and record.tenant_id != request.tenant_id:
            return None
        return record

    @staticmethod
    def _data_constraint(
        request: PermissionCheckRequest, record: DataRegistry | None
    ) -> EngineDecision | None:
        if record is None:
            if request.data_state != "active":
                return _decision(False, "DATA_STATE_DENIED")
            return None
        if record.data_label != request.data_label:
            return _decision(False, "DATA_LABEL_DENIED")
        if record.state != request.data_state or record.state != "active":
            return _decision(False, "DATA_STATE_DENIED")
        if request.action not in _json_list(record.allowed_actions_json):
            return _decision(False, "ACTION_NOT_GRANTED")
        return None

    @staticmethod
    def _resolve_person(
        session: Session, request: PermissionCheckRequest
    ) -> tuple[Person | None, EngineDecision | None]:
        query = select(Person).where(Person.actor_id == request.actor_id)
        if request.tenant_id:
            query = query.where(Person.tenant_id == request.tenant_id)
        people = list(session.scalars(query.order_by(Person.id)).all())
        if not people:
            return None, _decision(False, "USER_NOT_FOUND")
        if request.person_id:
            people = [item for item in people if item.id == request.person_id]
            if not people:
                return None, _decision(False, "PERSON_NOT_FOUND")
        if len(people) != 1 or people[0].status != "active":
            return None, _decision(False, "PERSON_NOT_FOUND")
        return people[0], None

    @staticmethod
    def _active_assignments(
        session: Session,
        request: PermissionCheckRequest,
        person_id: str,
        now: datetime,
    ) -> list[PersonPositionAssignment]:
        query = select(PersonPositionAssignment).where(
            PersonPositionAssignment.person_id == person_id,
            PersonPositionAssignment.actor_id == request.actor_id,
            PersonPositionAssignment.status == "active",
        )
        if request.tenant_id:
            query = query.where(PersonPositionAssignment.tenant_id == request.tenant_id)
        if request.position_id:
            query = query.where(PersonPositionAssignment.position_id == request.position_id)
        items = session.scalars(query.order_by(PersonPositionAssignment.id)).all()
        return [
            item
            for item in items
            if _active(item.effective_from, item.effective_to, now)
        ]

    @staticmethod
    def _registered_data_allow(
        record: DataRegistry | None, request: PermissionCheckRequest, person_id: str
    ) -> str | None:
        if record is None:
            return None
        owner_actions = {"create", "read", "fetch", "use", "store", "update"}
        participant_actions = {"read", "fetch", "use"}
        if record.owner_person_id == person_id and request.action in owner_actions:
            return f"data_owner:{record.id}:{request.action}"
        if (
            person_id in _json_list(record.initial_person_ids_json)
            and request.action in participant_actions
        ):
            return f"data_initial:{record.id}:{person_id}:{request.action}"
        return None

    @staticmethod
    def _position_standard_allow(
        session: Session,
        request: PermissionCheckRequest,
        position_ids: set[str],
        now: datetime,
    ) -> PositionStandardPermission | None:
        if not position_ids:
            return None
        items = session.scalars(
            select(PositionStandardPermission)
            .where(
                PositionStandardPermission.position_id.in_(position_ids),
                PositionStandardPermission.effect == "allow",
            )
            .order_by(PositionStandardPermission.id)
        ).all()
        return next(
            (
                item
                for item in items
                if _active(item.valid_from, item.valid_to, now)
                and _matches_common(item, request)
            ),
            None,
        )

    @staticmethod
    def _delegation_allow(
        session: Session,
        request: PermissionCheckRequest,
        person_id: str,
        now: datetime,
    ) -> DataDelegation | None:
        if not request.resource_id:
            return None
        items = session.scalars(
            select(DataDelegation)
            .where(
                DataDelegation.to_person_id == person_id,
                DataDelegation.resource_id == request.resource_id,
                DataDelegation.action == request.action,
            )
            .order_by(DataDelegation.id)
        ).all()
        return next(
            (
                item
                for item in items
                if _active(item.valid_from, item.valid_to, now)
                and _matches(item.resource_type, request.resource_type)
                and _matches(item.data_label, request.data_label)
                and request.data_state in _json_list(item.data_states_json)
            ),
            None,
        )

    @staticmethod
    def _institution_decision(
        session: Session,
        request: PermissionCheckRequest,
        person: Person,
        position_ids: set[str],
        now: datetime,
        *,
        effect: str,
    ) -> InstitutionPolicy | None:
        items = session.scalars(
            select(InstitutionPolicy)
            .where(
                InstitutionPolicy.tenant_id == person.tenant_id,
                InstitutionPolicy.effect == effect,
            )
            .order_by(InstitutionPolicy.priority.desc(), InstitutionPolicy.id)
        ).all()
        for item in items:
            subject_match = (
                item.subject_type == "any"
                or (item.subject_type == "person" and item.subject_id == person.id)
                or (item.subject_type == "actor" and item.subject_id == person.actor_id)
                or (item.subject_type == "position" and item.subject_id in position_ids)
            )
            if subject_match and _active(item.valid_from, item.valid_to, now) and _matches_common(item, request):
                return item
        return None

    @staticmethod
    def _manager_scope_allow(
        session: Session,
        request: PermissionCheckRequest,
        manager_person_id: str,
        owner_person_id: str,
    ) -> bool:
        if request.action not in {"read", "fetch"} or manager_person_id == owner_person_id:
            return False
        query = select(PersonManagerEdge).where(
            PersonManagerEdge.status == "active",
            PersonManagerEdge.tenant_id == (request.tenant_id or ""),
        )
        if request.domain_id:
            query = query.where(PersonManagerEdge.domain_id == request.domain_id)
        edges = session.scalars(query).all()
        children: dict[str, set[str]] = {}
        for edge in edges:
            children.setdefault(edge.manager_person_id, set()).add(edge.person_id)
        pending = list(children.get(manager_person_id, set()))
        seen: set[str] = set()
        while pending:
            person_id = pending.pop()
            if person_id == owner_person_id:
                return True
            if person_id in seen:
                continue
            seen.add(person_id)
            pending.extend(children.get(person_id, set()))
        return False

    def _has_expired_match(
        self,
        session: Session,
        request: PermissionCheckRequest,
        person: Person,
        position_ids: set[str],
        now: datetime,
    ) -> bool:
        standards = session.scalars(
            select(PositionStandardPermission).where(
                PositionStandardPermission.position_id.in_(position_ids),
                PositionStandardPermission.effect == "allow",
            )
        ).all()
        if any(
            _matches_common(item, request)
            and _utc(item.valid_to) is not None
            and _utc(item.valid_to) <= now
            for item in standards
        ):
            return True
        if request.resource_id:
            delegations = session.scalars(
                select(DataDelegation).where(
                    DataDelegation.to_person_id == person.id,
                    DataDelegation.resource_id == request.resource_id,
                    DataDelegation.action == request.action,
                )
            ).all()
            if any(
                _matches(item.data_label, request.data_label)
                and _utc(item.valid_to) is not None
                and _utc(item.valid_to) <= now
                for item in delegations
            ):
                return True
        policies = session.scalars(
            select(InstitutionPolicy).where(
                InstitutionPolicy.tenant_id == person.tenant_id,
                InstitutionPolicy.effect == "allow",
            )
        ).all()
        return any(
            _matches_common(item, request)
            and _utc(item.valid_to) is not None
            and _utc(item.valid_to) <= now
            for item in policies
        )

    @staticmethod
    def _has_action_match_for_other_label(
        session: Session, request: PermissionCheckRequest, position_ids: set[str]
    ) -> bool:
        if not position_ids:
            return False
        count = session.scalar(
            select(PositionStandardPermission.id)
            .where(
                PositionStandardPermission.position_id.in_(position_ids),
                PositionStandardPermission.action == request.action,
                PositionStandardPermission.data_label.not_in([request.data_label, "*"]),
            )
            .limit(1)
        )
        return count is not None
