from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Person(Base):
    __tablename__ = "persons"
    __table_args__ = (
        UniqueConstraint("tenant_id", "actor_id"),
        CheckConstraint("id = actor_id", name="ck_person_account_identity"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("tenant_id", "id"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PersonPositionAssignment(Base):
    __tablename__ = "person_position_assignments"
    __table_args__ = (
        CheckConstraint("person_id = actor_id", name="ck_assignment_account_identity"),
        Index(
            "uq_assignment_active_position",
            "position_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_assignment_person_active", "person_id", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("persons.id"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    position_id: Mapped[str] = mapped_column(ForeignKey("positions.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_by: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    ended_by: Mapped[str | None] = mapped_column(String(128))


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    dsm_actor_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PersonManagerEdge(Base):
    __tablename__ = "person_manager_edges"
    __table_args__ = (
        Index(
            "uq_manager_active_person_domain",
            "tenant_id",
            "domain_id",
            "person_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_manager_domain", "tenant_id", "domain_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("persons.id"), nullable=False)
    manager_person_id: Mapped[str] = mapped_column(ForeignKey("persons.id"), nullable=False)
    domain_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(128), default="system", nullable=False)


class PositionStandardPermission(Base):
    __tablename__ = "position_standard_permissions"
    __table_args__ = (Index("ix_position_permission_match", "position_id", "action"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    position_id: Mapped[str] = mapped_column(ForeignKey("positions.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    data_label: Mapped[str] = mapped_column(String(128), default="*", nullable=False)
    data_states_json: Mapped[str] = mapped_column(Text, default='["active"]', nullable=False)
    source_service: Mapped[str] = mapped_column(String(128), default="*", nullable=False)
    target_service: Mapped[str] = mapped_column(String(128), default="*", nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), default="*", nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), default="*", nullable=False)
    effect: Mapped[str] = mapped_column(String(16), default="allow", nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    basis: Mapped[str] = mapped_column(Text, default="岗位标准配置", nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), default="system", nullable=False)


class DataDelegation(Base):
    __tablename__ = "data_delegations"
    __table_args__ = (Index("ix_delegation_match", "to_person_id", "resource_id", "action"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    from_person_id: Mapped[str] = mapped_column(String(128), nullable=False)
    to_person_id: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), default="data", nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    data_label: Mapped[str] = mapped_column(String(128), default="*", nullable=False)
    data_states_json: Mapped[str] = mapped_column(Text, default='["active"]', nullable=False)
    can_redelegate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), default="system", nullable=False)


class InstitutionPolicy(Base):
    __tablename__ = "institution_policies"
    __table_args__ = (Index("ix_policy_match", "tenant_id", "action", "effect"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), default="any", nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), default="*", nullable=False)
    action: Mapped[str] = mapped_column(String(128), default="*", nullable=False)
    data_label: Mapped[str] = mapped_column(String(128), default="*", nullable=False)
    data_states_json: Mapped[str] = mapped_column(Text, default='["*"]', nullable=False)
    source_service: Mapped[str] = mapped_column(String(128), default="*", nullable=False)
    target_service: Mapped[str] = mapped_column(String(128), default="*", nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), default="*", nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), default="*", nullable=False)
    effect: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), default="system", nullable=False)


class ServiceCallRule(Base):
    __tablename__ = "service_call_rules"
    __table_args__ = (UniqueConstraint("source_service", "target_service", "action"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_service: Mapped[str] = mapped_column(String(128), nullable=False)
    target_service: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), default="*", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DataRegistry(Base):
    __tablename__ = "data_registry"
    __table_args__ = (
        CheckConstraint(
            "owner_person_id = owner_actor_id",
            name="ck_data_owner_account_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_person_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    data_label: Mapped[str] = mapped_column(String(128), default="normal", nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    allowed_actions_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    initial_person_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    business_tags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    storage_refs_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DataAction(Base):
    __tablename__ = "data_actions"

    action: Mapped[str] = mapped_column(String(128), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), default="normal", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResourceDirectory(Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint(
            "owner_person_id = owner_actor_id",
            name="ck_resource_owner_account_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    level: Mapped[str] = mapped_column(String(64), default="personal_position", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    owner_person_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_position_id: Mapped[str] = mapped_column(String(128), nullable=False)
    department_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResourcePublication(Base):
    __tablename__ = "resource_publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), nullable=False)
    target_level: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResourcePublicationGrant(Base):
    """Links an approved asset publication to its effective permission facts."""

    __tablename__ = "resource_publication_grants"
    __table_args__ = (UniqueConstraint("publication_id", "position_permission_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("resource_publications.id"), nullable=False)
    position_permission_id: Mapped[int] = mapped_column(ForeignKey("position_standard_permissions.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PermissionDecision(Base):
    __tablename__ = "permission_decisions"
    __table_args__ = (
        Index("ix_decision_trace", "trace_id", "id"),
        Index("ix_decision_request", "request_id", "id"),
        Index("ix_decision_actor", "actor_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    trace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    request_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    person_id: Mapped[str | None] = mapped_column(String(128))
    position_id: Mapped[str | None] = mapped_column(String(128))
    tenant_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    source_service: Mapped[str] = mapped_column(String(128), nullable=False)
    target_service: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(128))
    resource_id: Mapped[str | None] = mapped_column(String(255))
    data_label: Mapped[str] = mapped_column(String(128), nullable=False)
    data_state: Mapped[str] = mapped_column(String(32), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_id: Mapped[str | None] = mapped_column(String(255))
    four_factors_json: Mapped[str | None] = mapped_column(Text)
    error_json: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responsible_actor_id: Mapped[str | None] = mapped_column(String(128))
    executor_type: Mapped[str | None] = mapped_column(String(32))
    executor_id: Mapped[str | None] = mapped_column(String(128))
    original_caller_service_id: Mapped[str | None] = mapped_column(String(128))
    ingress_mode: Mapped[str | None] = mapped_column(String(64))
    transfer_id: Mapped[str | None] = mapped_column(String(255), index=True)
    identity_context_hash: Mapped[str | None] = mapped_column(String(128))
