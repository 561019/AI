from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Tuple

from l1_2_template_management.template_management import (
    InMemoryTemplateRepository,
    REGISTERED_SERVICES as L12_TEMPLATE_SERVICES,
    TemplateManagementService,
    seed_common_templates,
)


SERVICE_VERSION = "l2-flow-execution-engine.v0.1"

STANDARD_TASK_STATUSES = {"accepted", "in_progress", "waiting_human", "completed", "failed", "cancelled"}
INSTANCE_TRANSITIONS = {
    "accepted": {"in_progress", "waiting_human", "failed", "cancelled"},
    "in_progress": {"waiting_human", "completed", "failed", "cancelled"},
    "waiting_human": {"in_progress", "completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}
NODE_TRANSITIONS = {
    "pending": {"in_progress", "skipped"},
    "in_progress": {"waiting_human", "completed", "failed"},
    "waiting_human": {"pending", "completed", "failed"},
    "completed": {"pending"},
    "failed": {"pending"},
    "skipped": {"pending"},
}
HUMAN_TASK_TRANSITIONS = {"pending": {"done", "timed_out"}, "done": set(), "timed_out": set()}
DISPATCH_TASK_TRANSITIONS = {"accepted": {"in_progress", "completed", "failed"}, "in_progress": {"completed", "failed"}, "completed": set(), "failed": set()}
PLATFORM_STATUS_MAP = {
    "accepted": "已受理",
    "in_progress": "办理中",
    "waiting_human": "待真人确认",
    "completed": "已完成",
    "failed": "无法办理",
    "cancelled": "已取消",
}
FLOW_SERVICES = {
    "flow.start": {"request_type": "execute", "description": "Create and run a flow instance."},
    "flow.cancel": {"request_type": "execute", "description": "Cancel a non-terminal flow instance and close pending local human tasks."},
    "flow.get": {"request_type": "query", "description": "Read one flow instance."},
    "flow.list": {"request_type": "query", "description": "List flow instances by status/requester/template."},
    "flow.decide_human": {"request_type": "execute", "description": "Approve or reject a pending human task."},
    "flow.dispatch_status": {"request_type": "execute", "description": "Receive subtask status from a delegated engine."},
    "flow.retry_workbench_delivery": {"request_type": "execute", "description": "Retry a failed todo or notification delivery recorded in the instance outbox."},
    "flow.scan_delivery_retries": {"request_type": "execute", "description": "Retry eligible failed workbench deliveries up to their configured attempt limit."},
    "flow.audit": {"request_type": "query", "description": "Read instance audit events."},
    "flow.health": {"request_type": "query", "description": "Read L2 runtime health and backlog counters."},
    "flow.scan_timeouts": {"request_type": "execute", "description": "Scan waiting human tasks and apply their preset timeout policy."},
    "flow.design_from_text": {"request_type": "maintain", "description": "Create a flow-design draft from a natural-language request for the shared design UI."},
    "flow.design_get": {"request_type": "query", "description": "Read one flow-design draft."},
    "flow.design_list": {"request_type": "query", "description": "List flow-design drafts by requester, status, or flow kind."},
    "flow.design_update": {"request_type": "maintain", "description": "Update a flow-design draft after the user or AI revises it."},
    "flow.design_validate": {"request_type": "query", "description": "Check whether a fixed or flexible flow design is reasonable before running or templating."},
    "flow.design_convert_to_template": {"request_type": "maintain", "description": "Convert a confirmed flexible/fixed design draft into an L1.2 fixed-template draft."},
}
TEMPLATE_GATEWAY_SERVICES = {
    service_name: {
        "request_type": meta["request_type"],
        "description": f"Forward L4 template-maintenance request to L1.2: {meta['description']}",
    }
    for service_name, meta in L12_TEMPLATE_SERVICES.items()
}
FLOW_SERVICES.update(TEMPLATE_GATEWAY_SERVICES)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def deep_copy(value: Any) -> Any:
    return copy.deepcopy(value)


def normalize_id(value: str, prefix: str = "id") -> str:
    text = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip()).strip("_")
    return text or f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class EngineService:
    engine_id: str
    engine_name: str
    service_name: str
    request_type: str
    estimated_seconds: int
    enabled: bool = True
    capability_id: str = ""
    capability_dictionary_version: str = "2026.07.16"
    registry_version: str = "registry_2026.07.16"
    schema_version: str = "1.0"
    registration_status: str = "active"


@dataclass
class CapabilityDefinition:
    """The platform-wide capability dictionary: identifiers, not routing."""
    capability_id: str
    dictionary_version: str = "2026.07.16"
    name: str = ""
    status: str = "active"


@dataclass
class CapabilityRegistration:
    """The locally loaded capability registration: capability -> service wiring."""
    capability_id: str
    service_code: str
    action: str
    schema_version: str = "1.0"
    registry_version: str = "registry_2026.07.16"
    status: str = "active"
    allowed_callers: List[str] = field(default_factory=lambda: ["l2.workflow_execution"])
    concurrency_limit: int = 1


@dataclass
class ExecutionNode:
    node_id: str
    node_type: str
    name: str
    status: str = "pending"
    service_ref: str = ""
    condition_ref: str = ""
    branches: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    approval_position: str = ""
    notify_position: str = ""
    depends_on: List[str] = field(default_factory=list)
    max_retries: int = 0
    retry_count: int = 0
    dispatch_attempt: int = 0
    failure_policy: str = "fail"
    timeout_seconds: int = 0
    timeout_policy: str = "escalate_human"
    started_at: str = ""
    completed_at: str = ""
    output: Dict[str, Any] = field(default_factory=dict)
    capability_id: str = ""
    capability_dictionary_version: str = ""
    registry_version: str = ""
    schema_version: str = ""
    service_action: str = ""


@dataclass
class DispatchTask:
    task_id: str
    subtask_id: str
    node_id: str
    target_engine_id: str
    target_engine_name: str
    service_name: str
    request_type: str
    status: str
    payload: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    callback_sequence: int = 0


@dataclass
class HumanTask:
    task_id: str
    node_id: str
    mode: str
    position_id: str
    assignee_id: str
    assignee_name: str
    title: str
    summary: str
    status: str = "pending"
    decision: str = ""
    reason: str = ""
    created_at: str = field(default_factory=now_iso)
    decided_at: str = ""


@dataclass
class FlowInstance:
    instance_id: str
    trace_id: str
    requester_id: str
    scope_id: str
    request_text: str
    route_type: str
    status: str
    template_id: str = ""
    template_version: Optional[int] = None
    idempotency_key: str = ""
    current_nodes: List[str] = field(default_factory=list)
    nodes: List[ExecutionNode] = field(default_factory=list)
    dispatch_tasks: List[DispatchTask] = field(default_factory=list)
    human_tasks: List[HumanTask] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    audit_log: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class FlowDesignDraft:
    design_id: str
    requester_id: str
    source_text: str
    flow_kind: str
    status: str
    title: str
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    validation: Dict[str, Any] = field(default_factory=dict)
    candidate_template_id: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


class InstanceRepository(Protocol):
    def load_all(self) -> Dict[str, FlowInstance]:
        ...

    def load_designs(self) -> Dict[str, FlowDesignDraft]:
        ...

    def save_all(self, instances: Dict[str, FlowInstance], designs: Optional[Dict[str, FlowDesignDraft]] = None) -> None:
        ...


class InMemoryInstanceRepository:
    def __init__(self) -> None:
        self.instances: Dict[str, FlowInstance] = {}
        self.designs: Dict[str, FlowDesignDraft] = {}

    def load_all(self) -> Dict[str, FlowInstance]:
        return deep_copy(self.instances)

    def load_designs(self) -> Dict[str, FlowDesignDraft]:
        return deep_copy(self.designs)

    def save_all(self, instances: Dict[str, FlowInstance], designs: Optional[Dict[str, FlowDesignDraft]] = None) -> None:
        self.instances = deep_copy(instances)
        if designs is not None:
            self.designs = deep_copy(designs)


class JsonInstanceRepository:
    _path_locks: Dict[str, threading.RLock] = {}
    _path_locks_guard = threading.Lock()

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        with self._path_locks_guard:
            self._lock = self._path_locks.setdefault(str(self.path.resolve()), threading.RLock())

    def load_all(self) -> Dict[str, FlowInstance]:
        with self._lock:
            if not self.path.exists():
                return {}
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {key: self._from_dict(value) for key, value in raw.get("instances", {}).items()}

    def load_designs(self) -> Dict[str, FlowDesignDraft]:
        with self._lock:
            if not self.path.exists():
                return {}
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {key: FlowDesignDraft(**value) for key, value in raw.get("designs", {}).items()}

    def save_all(self, instances: Dict[str, FlowInstance], designs: Optional[Dict[str, FlowDesignDraft]] = None) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": SERVICE_VERSION,
                "instances": {key: self._to_dict(value) for key, value in instances.items()},
                "designs": {key: asdict(value) for key, value in (designs or {}).items()},
            }
            self._atomic_write(payload)

    def _atomic_write(self, payload: Dict[str, Any]) -> None:
        handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp", delete=False)
        try:
            with handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, self.path)
        finally:
            if os.path.exists(handle.name):
                os.unlink(handle.name)

    def _to_dict(self, instance: FlowInstance) -> Dict[str, Any]:
        return asdict(instance)

    def _from_dict(self, data: Dict[str, Any]) -> FlowInstance:
        data = dict(data)
        data["nodes"] = [ExecutionNode(**item) for item in data.get("nodes", [])]
        data["dispatch_tasks"] = [DispatchTask(**item) for item in data.get("dispatch_tasks", [])]
        data["human_tasks"] = [HumanTask(**item) for item in data.get("human_tasks", [])]
        data.setdefault("idempotency_key", "")
        data.setdefault("dispatch_tasks", [])
        return FlowInstance(**data)


class L12TemplateClient:
    """Local adapter for L1.2. Production should call through L1 interface-control."""

    def __init__(self, service: Optional[TemplateManagementService] = None) -> None:
        self.service = service or TemplateManagementService(InMemoryTemplateRepository())
        seed_common_templates(self.service)

    def retrieve(self, template_id: str, trace_id: str) -> Dict[str, Any]:
        response = self.service.handle_instruction(
            {
                "caller_layer": "L2",
                "service_name": "template.retrieve",
                "request_type": "query",
                "actor_id": "l2-flow-execution-engine",
                "payload": {
                    "actor_roles": ["l2_flow_engine"],
                    "template_id": template_id,
                    "purpose": "new_start",
                },
                "expected_return": "杩斿洖鍥哄畾娴佺▼妯℃澘瀹氫箟",
                "trace_id": trace_id,
            }
        )
        if not response.get("ok"):
            raise ValueError(response.get("error", {}).get("code") or "template_retrieve_failed")
        return response["result"]

    def forward_instruction(self, instruction: Dict[str, Any]) -> Dict[str, Any]:
        payload = instruction.get("payload") if isinstance(instruction.get("payload"), dict) else {}
        forwarded = {
            "caller_layer": "L2",
            "service_name": str(instruction.get("service_name") or ""),
            "request_type": str(instruction.get("request_type") or ""),
            "actor_id": str(instruction.get("actor_id") or payload.get("actor_id") or "l2-template-maintenance-gateway"),
            "payload": payload,
            "expected_return": "L1.2 template-management result forwarded through L2.",
            "trace_id": str(instruction.get("trace_id") or uuid.uuid4()),
        }
        return self.service.handle_instruction(forwarded)


class OrganizationDirectory(Protocol):
    """Port implemented by the platform's 1.1 organization and permission service."""

    def resolve(self, position_id: str) -> Dict[str, str]:
        ...


class DelegatedExecutor(Protocol):
    """Port for the real L2 specialist engines selected from ModuleRegistry."""

    def execute(self, service: EngineService, payload: Dict[str, Any]) -> Dict[str, Any]:
        ...


class WorkbenchGateway(Protocol):
    """Port for platform workbench/todo and notification delivery."""

    def create_task(self, task: HumanTask, trace_id: str) -> Dict[str, Any]:
        ...

    def send_notification(self, task: HumanTask, trace_id: str) -> Dict[str, Any]:
        ...


class HumanDecisionAuthorizer(Protocol):
    """Port for verifying the acting human or an authorized delegate for a workbench task."""

    def authorize(self, task: HumanTask, decided_by: str, decision_payload: Dict[str, Any]) -> bool:
        ...


class OrganizationResolver:
    """Deterministic local directory. Replace with an OrganizationDirectory in production."""
    def __init__(self, position_map: Optional[Dict[str, Dict[str, str]]] = None) -> None:
        self.position_map = position_map or {
            "finance_accrual_owner": {"person_id": "P_FIN_001", "name": "Finance owner"},
            "finance_owner": {"person_id": "P_FIN_001", "name": "Finance owner"},
            "finance_template_owner": {"person_id": "P_FIN_TEMPLATE_001", "name": "Finance template owner"},
            "procurement_template_owner": {"person_id": "P_PUR_001", "name": "Procurement owner"},
            "procurement_payment_owner": {"person_id": "P_PAY_001", "name": "Procurement payment owner"},
            "marketing_template_owner": {"person_id": "P_MKT_001", "name": "Marketing director"},
            "attendance_owner": {"person_id": "P_HR_001", "name": "HR owner"},
            "template_owner_unassigned": {"person_id": "P_OWNER_001", "name": "Flow owner"},
        }

    def resolve(self, position_id: str) -> Dict[str, str]:
        if position_id not in self.position_map:
            raise ValueError(f"position_unassigned:{position_id}")
        return self.position_map[position_id]


class ModuleRegistry:
    def __init__(
        self,
        services: Optional[Iterable[EngineService]] = None,
        capability_dictionary: Optional[Iterable[CapabilityDefinition]] = None,
        capability_registrations: Optional[Iterable[CapabilityRegistration]] = None,
    ) -> None:
        self.services: Dict[str, EngineService] = {}
        for item in services or self.default_services():
            self.services[item.service_name] = item
        default_dictionary = [
            CapabilityDefinition(
                capability_id=item.capability_id,
                dictionary_version=item.capability_dictionary_version,
                name=item.service_name,
                status="active" if item.enabled else "inactive",
            )
            for item in self.services.values() if item.capability_id
        ]
        default_registrations = [
            CapabilityRegistration(
                capability_id=item.capability_id,
                service_code=item.service_name,
                action=item.request_type,
                schema_version=item.schema_version,
                registry_version=item.registry_version,
                status=item.registration_status if item.enabled else "inactive",
            )
            for item in self.services.values() if item.capability_id
        ]
        self.capability_dictionary = {
            item.capability_id: item for item in (capability_dictionary or default_dictionary)
        }
        self.capability_registrations = {
            item.capability_id: item for item in (capability_registrations or default_registrations)
        }

    @staticmethod
    def default_services() -> List[EngineService]:
        return [
            EngineService("rule_engine", "Rule engine", "L2.rule_engine.contract_payment_match", "calculate", 8, capability_id="CAP.RULE.CONTRACT.PAYMENT.MATCH"),
            EngineService("rule_engine", "Rule engine", "L2.rule_engine.procurement_compare", "calculate", 10, capability_id="CAP.RULE.PROCUREMENT.COMPARE"),
            EngineService("rule_engine", "Rule engine", "L2.rule_engine.content_compliance_check", "calculate", 6, capability_id="CAP.RULE.CONTENT.COMPLIANCE.CHECK"),
            EngineService("data_operation", "Data operation engine", "L2.data.collect", "query", 10, capability_id="CAP.DATA.OPERATION.READ_AGGREGATE"),
            EngineService("external_system", "External system engine", "L2.external.oa_submit", "execute", 12, capability_id="CAP.SYSTEM.OA.SUBMIT"),
            EngineService("notification", "Notification engine", "L2.notify.send", "execute", 3, capability_id="CAP.NOTIFICATION.DISPATCH"),
            EngineService("content", "Content engine", "L2.content.generate", "execute", 15, capability_id="CAP.CONTENT.DRAFT.GENERATE"),
            EngineService("generic", "Generic execution engine", "L2.generic.execute", "execute", 8, capability_id="CAP.GENERIC.TASK.EXECUTE"),
        ]

    def resolve(self, service_ref: str) -> EngineService:
        if service_ref in self.services:
            return self.services[service_ref]
        if service_ref.startswith("L2.rule_engine"):
            return self.services["L2.rule_engine.procurement_compare"]
        if service_ref.startswith("L2.flow_execution"):
            return self.services["L2.generic.execute"]
        if service_ref.startswith("L2."):
            return self.services["L2.generic.execute"]
        raise ValueError(f"service_not_registered:{service_ref}")

    def resolve_capability(self, capability_id: str) -> Tuple[EngineService, CapabilityDefinition, CapabilityRegistration]:
        definition = self.capability_dictionary.get(capability_id)
        registration = self.capability_registrations.get(capability_id)
        if not definition or not registration:
            raise ValueError(f"capability_not_registered:{capability_id}")
        if definition.status != "active" or registration.status != "active":
            raise ValueError(f"capability_not_active:{capability_id}")
        service = self.services.get(registration.service_code)
        if not service or not service.enabled:
            raise ValueError(f"capability_not_active:{capability_id}")
        return service, definition, registration

    def capability_snapshot(self, capability_id: str) -> Dict[str, Any]:
        service, definition, registration = self.resolve_capability(capability_id)
        return {
            "capability_id": definition.capability_id,
            "capability_dictionary_version": definition.dictionary_version,
            "registry_version": registration.registry_version,
            "service_code": registration.service_code,
            "action": registration.action,
            "schema_version": registration.schema_version,
            "registration_status": registration.status,
            "allowed_callers": list(registration.allowed_callers),
            "concurrency_limit": registration.concurrency_limit,
            "engine_id": service.engine_id,
        }


class MockExecutor:
    """Local-only executor. A production deployment injects a DelegatedExecutor."""

    def execute(self, service: EngineService, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "ok": True,
            "engine_id": service.engine_id,
            "engine_name": service.engine_name,
            "service_name": service.service_name,
            "status": "completed",
            "summary": f"{service.engine_name} completed delegated task: {payload.get('task') or payload.get('node_name')}",
            "mock": True,
        }


class CallableExecutor:
    """Adapter for an interface-control client or specialist-engine SDK callback."""

    def __init__(self, dispatch: Callable[[EngineService, Dict[str, Any]], Dict[str, Any]]) -> None:
        self.dispatch = dispatch

    def execute(self, service: EngineService, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self.dispatch(service, deep_copy(payload))
        if not isinstance(result, dict):
            return {"ok": False, "summary": "delegated_executor_invalid_response"}
        return result


class LocalWorkbenchGateway:
    """Local delivery shim that makes the integration result explicit without external messages."""

    def create_task(self, task: HumanTask, trace_id: str) -> Dict[str, Any]:
        return {"ok": True, "delivery": "local", "workbench_task_id": task.task_id, "trace_id": trace_id}

    def send_notification(self, task: HumanTask, trace_id: str) -> Dict[str, Any]:
        return {"ok": True, "delivery": "local", "notification_id": task.task_id, "trace_id": trace_id}


class LocalHumanDecisionAuthorizer:
    """Demo policy: only the current assigned person may decide a task."""

    def authorize(self, task: HumanTask, decided_by: str, decision_payload: Dict[str, Any]) -> bool:
        return bool(decided_by) and decided_by == task.assignee_id


class FlowExecutionEngine:
    def __init__(
        self,
        repository: Optional[InstanceRepository] = None,
        template_client: Optional[L12TemplateClient] = None,
        organization: Optional[OrganizationDirectory] = None,
        registry: Optional[ModuleRegistry] = None,
        executor: Optional[DelegatedExecutor] = None,
        workbench: Optional[WorkbenchGateway] = None,
        decision_authorizer: Optional[HumanDecisionAuthorizer] = None,
    ) -> None:
        self.repository = repository or InMemoryInstanceRepository()
        self.instances = self.repository.load_all()
        self.design_drafts = self.repository.load_designs()
        self.template_client = template_client or L12TemplateClient()
        self.organization = organization or OrganizationResolver()
        self.registry = registry or ModuleRegistry()
        self.executor = executor or MockExecutor()
        self.workbench = workbench or LocalWorkbenchGateway()
        self.decision_authorizer = decision_authorizer or LocalHumanDecisionAuthorizer()

    def service_registry(self) -> Dict[str, Any]:
        return {
            "module": "L2 娴佺▼鎵ц寮曟搸",
            "version": SERVICE_VERSION,
            "boundary": "L2 runs flow instances and acts as the business gateway for fixed-template maintenance; L1.2 remains the system of record for template definitions.",
            "services": deep_copy(FLOW_SERVICES),
            "module_registry": [asdict(item) for item in self.registry.services.values()],
            "capability_dictionary": [asdict(item) for item in self.registry.capability_dictionary.values()],
            "capability_registrations": [asdict(item) for item in self.registry.capability_registrations.values()],
            "integration_ports": {
                "template_client": "L1.2 template client through L1 interface-control in production.",
                "organization_directory": "1.1 organization and permission service.",
                "delegated_executor": "Registered L2 specialist engine adapter.",
                "workbench_gateway": "Platform notification and todo/workbench adapter.",
            },
        }

    def handle_instruction(self, instruction: Dict[str, Any]) -> Dict[str, Any]:
        trace_id = str(instruction.get("trace_id") or uuid.uuid4())
        service_name = str(instruction.get("service_name") or "")
        request_type = str(instruction.get("request_type") or "")
        payload = instruction.get("payload") if isinstance(instruction.get("payload"), dict) else {}
        if service_name not in FLOW_SERVICES:
            return self._error(trace_id, service_name, "service_not_registered")
        expected_type = FLOW_SERVICES[service_name]["request_type"]
        if request_type != expected_type:
            return self._error(trace_id, service_name, f"request_type_must_be_{expected_type}")
        if service_name.startswith("template."):
            return self.template_client.forward_instruction(
                {
                    **instruction,
                    "trace_id": trace_id,
                    "service_name": service_name,
                    "request_type": request_type,
                    "payload": payload,
                }
            )
        try:
            if service_name == "flow.start":
                result = self.start({**payload, "trace_id": trace_id})
            elif service_name == "flow.cancel":
                result = self.cancel(str(payload.get("instance_id") or ""), str(payload.get("reason") or ""), str(instruction.get("actor_id") or payload.get("cancelled_by") or ""))
            elif service_name == "flow.get":
                result = self.get(str(payload.get("instance_id") or ""))
            elif service_name == "flow.list":
                result = self.list_instances(payload)
            elif service_name == "flow.decide_human":
                result = self.decide_human(
                    str(payload.get("instance_id") or ""),
                    str(payload.get("task_id") or ""),
                    str(payload.get("decision") or ""),
                    str(payload.get("reason") or ""),
                    str(payload.get("decided_by") or instruction.get("actor_id") or ""),
                    payload.get("decision_payload") if isinstance(payload.get("decision_payload"), dict) else {},
                )
            elif service_name == "flow.dispatch_status":
                result = self.dispatch_status(
                    str(payload.get("instance_id") or ""),
                    str(payload.get("subtask_id") or ""),
                    str(payload.get("status") or ""),
                    payload.get("result") if isinstance(payload.get("result"), dict) else {},
                    str(payload.get("callback_id") or ""),
                    int(payload.get("callback_sequence") or 0),
                )
            elif service_name == "flow.retry_workbench_delivery":
                result = self.retry_workbench_delivery(str(payload.get("instance_id") or ""), str(payload.get("delivery_id") or ""))
            elif service_name == "flow.scan_delivery_retries":
                result = self.scan_delivery_retries(payload)
            elif service_name == "flow.audit":
                result = self.audit(str(payload.get("instance_id") or ""), int(payload.get("limit") or 50))
            elif service_name == "flow.health":
                result = self.health()
            elif service_name == "flow.scan_timeouts":
                result = self.scan_timeouts(payload)
            elif service_name == "flow.design_from_text":
                result = self.design_from_text(payload)
            elif service_name == "flow.design_get":
                result = self.design_get(str(payload.get("design_id") or ""))
            elif service_name == "flow.design_list":
                result = self.design_list(payload)
            elif service_name == "flow.design_update":
                result = self.design_update(payload)
            elif service_name == "flow.design_validate":
                result = self.design_validate(str(payload.get("design_id") or ""), payload.get("design") if isinstance(payload.get("design"), dict) else None)
            elif service_name == "flow.design_convert_to_template":
                result = self.design_convert_to_template(payload, str(instruction.get("actor_id") or ""))
            else:
                result = {}
        except ValueError as exc:
            return self._error(trace_id, service_name, str(exc))
        return {"ok": True, "trace_id": trace_id, "service_version": SERVICE_VERSION, "service_name": service_name, "result": result}

    def start(self, request: Dict[str, Any]) -> Dict[str, Any]:
        trace_id = str(request.get("trace_id") or uuid.uuid4())
        requester_id = str(request.get("requester_id") or "")
        if not requester_id:
            raise ValueError("requester_id_required")
        idempotency_key = str(request.get("idempotency_key") or "").strip()
        if idempotency_key:
            existing = next((item for item in self.instances.values() if item.requester_id == requester_id and item.idempotency_key == idempotency_key), None)
            if existing:
                self._log(existing, "idempotent_replay", "閲嶅鍙戣捣鍛戒腑骞傜瓑閿紝杩斿洖宸叉湁瀹炰緥", {"idempotency_key": idempotency_key})
                self._persist()
                return self._public_instance(existing)
        request_text = str(request.get("request_text") or "")
        intent_result = request.get("intent_result") if isinstance(request.get("intent_result"), dict) else {}
        route = self._route(request_text, intent_result)
        instance = FlowInstance(
            instance_id=f"flow_{uuid.uuid4().hex[:12]}",
            trace_id=trace_id,
            requester_id=requester_id,
            scope_id=str(request.get("scope_id") or ""),
            request_text=request_text,
            route_type=route["route_type"],
            status="accepted",
            idempotency_key=idempotency_key,
        )
        self._log(instance, "accepted", "Flow execution engine accepted the request.", route)
        if route["route_type"] == "fixed_template_missing":
            self._transition_instance(instance, "waiting_human")
            instance.artifacts["exception"] = route["reason"]
            self._create_exception_task(instance, route["reason"])
        elif route["route_type"] == "fixed_template":
            self._load_fixed_template_plan(instance, route["template_id"])
            self._run_until_pause_or_done(instance)
        else:
            self._create_dynamic_plan(instance, request_text, intent_result)
            self._run_until_pause_or_done(instance)
        self.instances[instance.instance_id] = instance
        self._persist()
        return self._public_instance(instance)

    def get(self, instance_id: str) -> Dict[str, Any]:
        return self._public_instance(self._instance(instance_id))

    def cancel(self, instance_id: str, reason: str, cancelled_by: str) -> Dict[str, Any]:
        instance = self._instance(instance_id)
        if instance.status in {"completed", "failed", "cancelled"}:
            raise ValueError("terminal_instance_cannot_be_cancelled")
        for task in instance.human_tasks:
            if task.status == "pending":
                self._transition_human_task(task, "done")
                task.decision = "cancelled"
                task.reason = reason or "cancelled"
                task.decided_at = now_iso()
        active_dispatches = [task.subtask_id for task in instance.dispatch_tasks if task.status in {"accepted", "in_progress"}]
        self._transition_instance(instance, "cancelled")
        instance.current_nodes = []
        instance.artifacts["final_result"] = {"type": "cancelled", "reason": reason, "cancelled_by": cancelled_by, "cancelled_at": now_iso()}
        instance.artifacts["external_cancellation_required"] = active_dispatches
        self._log(instance, "cancelled", "Flow instance cancelled.", instance.artifacts["final_result"])
        self._persist()
        return self._public_instance(instance)

    def list_instances(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        requester_id = str(filters.get("requester_id") or "")
        status = str(filters.get("status") or "")
        template_id = str(filters.get("template_id") or "")
        items = []
        for instance in self.instances.values():
            if requester_id and instance.requester_id != requester_id:
                continue
            if status and instance.status != status:
                continue
            if template_id and instance.template_id != template_id:
                continue
            public = self._public_instance(instance)
            items.append({key: public[key] for key in ["instance_id", "trace_id", "requester_id", "status", "route_type", "template_id", "template_version", "current_step", "updated_at"]})
        offset = max(0, int(filters.get("offset") or 0))
        limit = min(200, max(1, int(filters.get("limit") or 50)))
        ordered = sorted(items, key=lambda item: item["updated_at"], reverse=True)
        return {"items": ordered[offset:offset + limit], "count": len(items), "offset": offset, "limit": limit}

    def audit(self, instance_id: str, limit: int = 50) -> Dict[str, Any]:
        instance = self._instance(instance_id)
        bounded_limit = min(200, max(1, limit))
        return {"instance_id": instance.instance_id, "items": instance.audit_log[-bounded_limit:], "limit": bounded_limit}

    def health(self) -> Dict[str, Any]:
        status_counts = {status: 0 for status in STANDARD_TASK_STATUSES}
        pending_human = 0
        failed_dispatches = 0
        pending_delivery_retries = 0
        dead_letter_deliveries = 0
        for instance in self.instances.values():
            status_counts[instance.status] = status_counts.get(instance.status, 0) + 1
            pending_human += sum(task.status == "pending" for task in instance.human_tasks)
            failed_dispatches += sum(task.status == "failed" for task in instance.dispatch_tasks)
            for delivery in instance.artifacts.get("workbench_deliveries", []):
                pending_delivery_retries += delivery.get("status") == "pending_retry"
                dead_letter_deliveries += delivery.get("status") == "dead_letter"
        return {
            "service_version": SERVICE_VERSION,
            "instance_status_counts": status_counts,
            "pending_human_tasks": pending_human,
            "failed_dispatch_tasks": failed_dispatches,
            "pending_delivery_retries": pending_delivery_retries,
            "dead_letter_deliveries": dead_letter_deliveries,
            "healthy": dead_letter_deliveries == 0,
            "checked_at": now_iso(),
        }

    def scan_timeouts(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = self._parse_time(str(payload.get("now") or now_iso()))
        timed_out = []
        for instance in self.instances.values():
            if instance.status != "waiting_human":
                continue
            for task in [item for item in instance.human_tasks if item.status == "pending"]:
                if task.node_id == "exception":
                    continue
                node = self._node(instance, task.node_id)
                if node.timeout_seconds <= 0 or not node.started_at:
                    continue
                elapsed_seconds = (now - self._parse_time(node.started_at)).total_seconds()
                if elapsed_seconds < node.timeout_seconds:
                    continue
                self._transition_human_task(task, "timed_out")
                node.output["timeout"] = {
                    "timed_out_at": now.isoformat(),
                    "elapsed_seconds": int(elapsed_seconds),
                    "timeout_seconds": node.timeout_seconds,
                    "timeout_policy": node.timeout_policy,
                }
                if node.timeout_policy == "fail":
                    self._transition_node(node, "failed")
                    self._transition_instance(instance, "failed")
                    instance.current_nodes = [node.node_id]
                    instance.artifacts["final_result"] = f"Human task timed out: {node.name}"
                    self._log(instance, "human_task_timeout_failed", node.name, node.output["timeout"])
                else:
                    self._transition_node(node, "waiting_human")
                    instance.artifacts["exception"] = f"Human task timed out: {node.name}"
                    self._create_exception_task(instance, instance.artifacts["exception"])
                    self._log(instance, "human_task_timeout_escalated", node.name, node.output["timeout"])
                timed_out.append({"instance_id": instance.instance_id, "task_id": task.task_id, "node_id": node.node_id, "policy": node.timeout_policy})
                break
        if timed_out:
            self._persist()
        return {"scanned_at": now.isoformat(), "timed_out": timed_out, "count": len(timed_out)}

    def design_from_text(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        requester_id = str(payload.get("requester_id") or "")
        if not requester_id:
            raise ValueError("requester_id_required")
        text = str(payload.get("request_text") or "")
        if not text.strip():
            raise ValueError("request_text_required")
        flow_kind = str(payload.get("flow_kind") or "auto")
        intent_result = payload.get("intent_result") if isinstance(payload.get("intent_result"), dict) else {}
        route = self._route(text, intent_result)
        if flow_kind == "auto":
            flow_kind = "fixed" if route["route_type"] in {"fixed_template", "fixed_template_missing"} else "flexible"
        nodes = self._draft_nodes_from_text(text, flow_kind)
        draft = FlowDesignDraft(
            design_id=f"design_{uuid.uuid4().hex[:12]}",
            requester_id=requester_id,
            source_text=text,
            flow_kind=flow_kind,
            status="draft",
            title=str(payload.get("title") or self._design_title(text, flow_kind)),
            nodes=nodes,
            candidate_template_id=str(route.get("template_id") or ""),
        )
        draft.validation = self._validate_design(asdict(draft))
        self.design_drafts[draft.design_id] = draft
        self._persist()
        return self._public_design(draft)

    def design_get(self, design_id: str) -> Dict[str, Any]:
        return self._public_design(self._design(design_id))

    def design_list(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        requester_id = str(filters.get("requester_id") or "")
        status = str(filters.get("status") or "")
        flow_kind = str(filters.get("flow_kind") or "")
        items = []
        for draft in self.design_drafts.values():
            if requester_id and draft.requester_id != requester_id:
                continue
            if status and draft.status != status:
                continue
            if flow_kind and draft.flow_kind != flow_kind:
                continue
            public = self._public_design(draft)
            items.append({
                "design_id": public["design_id"],
                "requester_id": public["requester_id"],
                "flow_kind": public["flow_kind"],
                "status": public["status"],
                "title": public["title"],
                "valid": public["validation"].get("valid"),
                "score": public["validation"].get("score"),
                "candidate_template_id": public["candidate_template_id"],
                "updated_at": public["updated_at"],
            })
        offset = max(0, int(filters.get("offset") or 0))
        limit = min(200, max(1, int(filters.get("limit") or 50)))
        ordered = sorted(items, key=lambda item: item["updated_at"], reverse=True)
        return {"items": ordered[offset:offset + limit], "count": len(items), "offset": offset, "limit": limit}

    def design_update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        design_id = str(payload.get("design_id") or "")
        draft = self._design(design_id)
        design = payload.get("design") if isinstance(payload.get("design"), dict) else {}
        if "title" in design:
            draft.title = str(design.get("title") or draft.title)
        if "flow_kind" in design:
            draft.flow_kind = str(design.get("flow_kind") or draft.flow_kind)
        if "nodes" in design:
            nodes = design.get("nodes")
            if not isinstance(nodes, list):
                raise ValueError("design_nodes_must_be_list")
            draft.nodes = deep_copy(nodes)
        draft.updated_at = now_iso()
        draft.validation = self._validate_design(asdict(draft))
        self._persist()
        return self._public_design(draft)

    def design_validate(self, design_id: str, inline_design: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if inline_design is not None:
            return self._validate_design(inline_design)
        draft = self._design(design_id)
        draft.validation = self._validate_design(asdict(draft))
        draft.updated_at = now_iso()
        self._persist()
        return self._public_design(draft)["validation"]

    def design_convert_to_template(self, payload: Dict[str, Any], actor_id: str) -> Dict[str, Any]:
        design_id = str(payload.get("design_id") or "")
        draft = self._design(design_id)
        validation = self._validate_design(asdict(draft))
        if validation["blockers"]:
            raise ValueError("design_has_validation_blockers")
        confirmation = payload.get("human_confirmation") if isinstance(payload.get("human_confirmation"), dict) else {}
        if confirmation.get("confirmed") is not True:
            raise ValueError("human_confirmation_required")
        template_id = normalize_id(str(payload.get("template_id") or draft.title), prefix="template")
        definition = self._template_definition_from_design(draft, template_id, payload)
        forwarded = self.template_client.forward_instruction(
            {
                "caller_layer": "L4",
                "service_name": "template.register_draft",
                "request_type": "maintain",
                "actor_id": actor_id or draft.requester_id,
                "payload": {
                    "actor_roles": payload.get("actor_roles") or ["template_maintainer"],
                    "template_id": template_id,
                    "definition": definition,
                },
                "trace_id": str(payload.get("trace_id") or uuid.uuid4()),
            }
        )
        if not forwarded.get("ok"):
            raise ValueError(forwarded.get("error", {}).get("code") or "template_register_failed")
        draft.status = "converted_to_template_draft"
        draft.updated_at = now_iso()
        self._persist()
        return {
            "design": self._public_design(draft),
            "template_register_result": forwarded["result"],
            "handoff": "L2 created the template draft content; L1.2 validated and stored it as a fixed-template draft. Publishing still requires separate human confirmation.",
        }

    def decide_human(
        self,
        instance_id: str,
        task_id: str,
        decision: str,
        reason: str,
        decided_by: str,
        decision_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        instance = self._instance(instance_id)
        task = next((item for item in instance.human_tasks if item.task_id == task_id), None)
        if not task:
            raise ValueError("human_task_not_found")
        if task.status != "pending":
            raise ValueError("human_task_already_decided")
        if decision not in {"approved", "rejected", "reject", "modified", "modify", "answered", "answer"}:
            raise ValueError("decision_must_be_approved_rejected_modified_or_answered")
        if not self.decision_authorizer.authorize(task, decided_by, decision_payload or {}):
            raise ValueError("human_task_decision_not_authorized")
        if task.mode == "exception_review":
            return self._decide_exception_task(instance, task, decision, reason, decided_by, decision_payload or {})
        self._transition_human_task(task, "done")
        task.decision = decision
        task.reason = reason
        task.decided_at = now_iso()
        node = self._node(instance, task.node_id)
        node.output["human_decision"] = {
            "decision": decision,
            "reason": reason,
            "decided_by": decided_by,
            "decided_at": task.decided_at,
            "assignee_id": task.assignee_id,
            "decision_payload": deep_copy(decision_payload or {}),
        }
        if decision == "approved":
            self._transition_node(node, "completed")
            node.completed_at = now_iso()
            self._transition_instance(instance, "in_progress")
            self._log(instance, "human_approved", f"{task.assignee_name} approved.", node.output["human_decision"])
            self._run_until_pause_or_done(instance)
        elif decision in {"rejected", "reject"}:
            self._log(instance, "human_rejected", f"{task.assignee_name} rejected.", node.output["human_decision"])
            handled = self._apply_rejection_policy(instance, node, task, reason)
            if handled:
                self._run_until_pause_or_done(instance)
            else:
                self._transition_node(node, "failed")
                self._transition_instance(instance, "failed")
                instance.artifacts["final_result"] = f"Rejected by human: {reason}"
        elif decision in {"modified", "modify"}:
            self._transition_node(node, "completed")
            node.completed_at = now_iso()
            instance.artifacts.setdefault("human_modifications", []).append(
                {
                    "node_id": node.node_id,
                    "task_id": task.task_id,
                    "modified_by": decided_by,
                    "reason": reason,
                    "payload": deep_copy(decision_payload or {}),
                    "at": task.decided_at,
                }
            )
            self._transition_instance(instance, "in_progress")
            self._log(instance, "human_modified_and_approved", f"{task.assignee_name} modified and continued.", node.output["human_decision"])
            self._run_until_pause_or_done(instance)
        elif decision in {"answered", "answer"}:
            self._transition_node(node, "completed")
            node.completed_at = now_iso()
            self._transition_instance(instance, "completed")
            instance.current_nodes = []
            instance.artifacts["final_result"] = {
                "type": "human_direct_answer",
                "answered_by": decided_by,
                "answer": str((decision_payload or {}).get("answer") or reason),
                "answered_at": task.decided_at,
            }
            self._log(instance, "human_direct_answer", f"{task.assignee_name} answered directly.", instance.artifacts["final_result"])
        instance.updated_at = now_iso()
        self._persist()
        return self._public_instance(instance)

    def dispatch_status(self, instance_id: str, subtask_id: str, status: str, result: Dict[str, Any], callback_id: str = "", callback_sequence: int = 0) -> Dict[str, Any]:
        if status not in STANDARD_TASK_STATUSES:
            raise ValueError("dispatch_status_not_standard")
        instance = self._instance(instance_id)
        if instance.status == "cancelled":
            self._log(instance, "dispatch_callback_ignored_after_cancel", f"Ignored callback after cancellation: {subtask_id}", {"callback_id": callback_id, "status": status})
            self._persist()
            return self._public_instance(instance)
        callback_id = callback_id or f"{subtask_id}:{status}:{json.dumps(result, ensure_ascii=False, sort_keys=True)}"
        known_callbacks = instance.artifacts.setdefault("dispatch_callback_ids", [])
        if callback_id in known_callbacks:
            self._log(instance, "dispatch_callback_duplicate", f"Ignored duplicate callback: {subtask_id}", {"callback_id": callback_id})
            self._persist()
            return self._public_instance(instance)
        task = next((item for item in instance.dispatch_tasks if item.subtask_id == subtask_id), None)
        if not task:
            raise ValueError("dispatch_task_not_found")
        if callback_sequence and callback_sequence <= task.callback_sequence:
            self._log(instance, "dispatch_callback_stale", f"Ignored stale callback: {subtask_id}", {"callback_id": callback_id, "callback_sequence": callback_sequence, "last_sequence": task.callback_sequence})
            self._persist()
            return self._public_instance(instance)
        if task:
            if status in DISPATCH_TASK_TRANSITIONS.get(task.status, set()):
                self._transition_dispatch_task(task, status)
            elif status != task.status:
                raise ValueError(f"invalid_dispatch_task_transition:{task.status}_to_{status}")
        task.result = deep_copy(result)
        task.updated_at = now_iso()
        if callback_sequence:
            task.callback_sequence = callback_sequence
            node = self._node(instance, task.node_id)
            node.output["dispatch_callback"] = deep_copy(result)
            if status == "completed":
                self._transition_node(node, "completed")
            elif status == "failed":
                self._transition_node(node, "failed")
        known_callbacks.append(callback_id)
        instance.artifacts.setdefault("dispatch_callbacks", []).append(
            {"callback_id": callback_id, "callback_sequence": callback_sequence, "subtask_id": subtask_id, "status": status, "result": deep_copy(result), "reported_at": now_iso()}
        )
        self._log(instance, "dispatch_status", f"Delegated engine callback: {subtask_id} {status}", result)
        self._persist()
        return self._public_instance(instance)

    def _decide_exception_task(self, instance: FlowInstance, task: HumanTask, decision: str, reason: str, decided_by: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._transition_human_task(task, "done")
        task.decision = decision
        task.reason = reason
        task.decided_at = now_iso()
        evidence = {"decision": decision, "reason": reason, "decided_by": decided_by, "decided_at": task.decided_at, "decision_payload": deep_copy(payload)}
        if decision in {"approved", "modified", "modify"}:
            failed_nodes = [node for node in instance.nodes if node.status == "failed"]
            if failed_nodes:
                target = failed_nodes[-1]
                self._transition_node(target, "pending")
                target.output = {"exception_retry": evidence}
                self._transition_instance(instance, "in_progress")
                self._log(instance, "exception_retry_approved", f"Retrying failed node: {target.name}", evidence)
                self._run_until_pause_or_done(instance)
            else:
                self._transition_instance(instance, "failed")
                instance.artifacts["final_result"] = {"type": "exception_reviewed", **evidence}
                self._log(instance, "exception_review_terminated", "No failed node available for retry.", evidence)
        elif decision in {"answered", "answer"}:
            self._transition_instance(instance, "completed")
            instance.current_nodes = []
            instance.artifacts["final_result"] = {"type": "exception_human_answer", "answer": str(payload.get("answer") or reason), **evidence}
            self._log(instance, "exception_direct_answer", "Human answered exception directly.", evidence)
        else:
            self._transition_instance(instance, "failed")
            instance.artifacts["final_result"] = {"type": "exception_terminated", **evidence}
            self._log(instance, "exception_terminated", "Human terminated exception.", evidence)
        self._persist()
        return self._public_instance(instance)

    def _draft_nodes_from_text(self, text: str, flow_kind: str) -> List[Dict[str, Any]]:
        lowered = text.lower()
        nodes: List[Dict[str, Any]] = [
            {
                "node_id": "understand_request",
                "type": "auto",
                "name": "理解发起人需求并整理执行材料",
                "service_ref": "L2.intent.prepare_flow_context",
            }
        ]
        if any(word in text for word in ["比价", "报价", "供应商", "采购"]) or any(word in lowered for word in ["purchase", "supplier", "quote"]):
            nodes.extend(
                [
                    {"node_id": "collect_supplier_data", "type": "auto", "name": "收集供应商与报价资料", "service_ref": "L2.data.collect_supplier_quotes"},
                    {"node_id": "rule_check", "type": "condition", "name": "按预算和资质规则判断分支", "condition_ref": "procurement_budget_and_qualification_policy"},
                    {"node_id": "budget_approval", "type": "human_approval", "name": "超预算或高风险事项真人拍板", "approval_position": "procurement_template_owner"},
                ]
            )
        elif any(word in text for word in ["发布", "公众号", "官网", "邮件", "营销", "促销"]) or any(word in lowered for word in ["marketing", "publish", "website", "mail"]):
            nodes.extend(
                [
                    {"node_id": "content_generate", "type": "auto", "name": "生成并自检对外内容", "service_ref": "L2.content.generate"},
                    {"node_id": "risk_check", "type": "condition", "name": "违禁词和对外发布风险检查", "condition_ref": "marketing_release_risk_policy"},
                    {"node_id": "release_approval", "type": "human_approval", "name": "对外发布前真人终审", "approval_position": "marketing_template_owner"},
                    {"node_id": "multi_channel_publish", "type": "auto", "name": "多渠道并联发布", "service_ref": "L2.external.oa_submit"},
                ]
            )
        else:
            nodes.extend(
                [
                    {"node_id": "execute_task", "type": "auto", "name": "调度合适 Agent 或 Skill 执行任务", "service_ref": "L2.generic.execute"},
                    {"node_id": "summarize_result", "type": "auto", "name": "汇总执行结果并返回发起人", "service_ref": "L2.generic.execute"},
                ]
            )
        if flow_kind == "fixed" and not any(node.get("type") == "human_approval" for node in nodes):
            nodes.append({"node_id": "fixed_flow_owner_confirm", "type": "human_approval", "name": "固定流程责任岗位确认", "approval_position": "template_owner_unassigned"})
        return nodes

    def _design_title(self, text: str, flow_kind: str) -> str:
        compact = " ".join(text.strip().split())
        if not compact:
            return f"{flow_kind} flow design"
        return compact[:40]

    def _validate_design(self, design: Dict[str, Any]) -> Dict[str, Any]:
        blockers: List[str] = []
        warnings: List[str] = []
        nodes = design.get("nodes")
        flow_kind = str(design.get("flow_kind") or "flexible")
        source_text = str(design.get("source_text") or design.get("request_text") or "")
        if flow_kind not in {"fixed", "flexible"}:
            blockers.append("flow_kind_must_be_fixed_or_flexible")
        if not isinstance(nodes, list) or not nodes:
            blockers.append("design_nodes_required")
            nodes = []
        node_ids = set()
        human_count = 0
        condition_count = 0
        for index, node in enumerate(nodes, 1):
            if not isinstance(node, dict):
                blockers.append(f"node_{index}_must_be_object")
                continue
            node_id = str(node.get("node_id") or "")
            node_type = str(node.get("type") or "")
            if not node_id:
                blockers.append(f"node_{index}_node_id_required")
            elif node_id in node_ids:
                blockers.append(f"node_{index}_node_id_duplicate")
            node_ids.add(node_id)
            if node_type not in {"auto", "condition", "human_approval", "human_notify"}:
                blockers.append(f"node_{index}_type_invalid")
            if node_type == "auto" and not (node.get("service_ref") or node.get("l2_engine_ref")):
                blockers.append(f"node_{index}_service_ref_required")
            if node_type == "condition":
                condition_count += 1
                if not node.get("condition_ref"):
                    blockers.append(f"node_{index}_condition_ref_required")
            if node_type == "human_approval":
                human_count += 1
                if not node.get("approval_position"):
                    blockers.append(f"node_{index}_approval_position_required")
            if node_type == "human_notify" and not node.get("notify_position"):
                blockers.append(f"node_{index}_notify_position_required")
            for person_field in ["person_id", "approver_person_id", "assignee_person_id", "recipient_person_id"]:
                if node.get(person_field):
                    blockers.append(f"node_{index}_must_store_position_not_person")
        dependency_graph: Dict[str, List[str]] = {}
        for index, node in enumerate(nodes, 1):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("node_id") or "")
            dependencies = node.get("depends_on") or []
            if not isinstance(dependencies, list):
                blockers.append(f"node_{index}_depends_on_must_be_list")
                continue
            normalized_dependencies = [str(value) for value in dependencies]
            if node_id and node_id in normalized_dependencies:
                blockers.append(f"node_{index}_cannot_depend_on_self")
            for dependency in normalized_dependencies:
                if dependency not in node_ids:
                    blockers.append(f"node_{index}_depends_on_unknown_node")
            if node_id:
                dependency_graph[node_id] = normalized_dependencies
        if self._has_design_dependency_cycle(dependency_graph):
            blockers.append("design_dependency_cycle_detected")
        for index, node in enumerate(nodes, 1):
            if not isinstance(node, dict) or str(node.get("type") or "") != "condition":
                continue
            node_id = str(node.get("node_id") or "")
            branches = node.get("branches") or {}
            if not isinstance(branches, dict):
                blockers.append(f"node_{index}_branches_must_be_object")
                continue
            for branch_name, branch in branches.items():
                if not isinstance(branch, dict):
                    blockers.append(f"node_{index}_branch_{branch_name}_must_be_object")
                    continue
                activated = {str(item) for item in branch.get("activate") or []}
                skipped = {str(item) for item in branch.get("skip") or []}
                if activated & skipped:
                    blockers.append(f"node_{index}_branch_{branch_name}_target_cannot_be_both_activated_and_skipped")
                for target_id in activated | skipped:
                    if target_id not in node_ids:
                        blockers.append(f"node_{index}_branch_{branch_name}_target_unknown_node")
                        continue
                    target = next((item for item in nodes if isinstance(item, dict) and str(item.get("node_id") or "") == target_id), {})
                    if node_id not in [str(item) for item in target.get("depends_on") or []]:
                        blockers.append(f"node_{index}_branch_target_must_depend_on_condition")
        critical_words = ["付款", "报销", "采购", "预算", "合同", "用印", "审批", "对外发布", "提成", "金额"]
        critical = any(word in source_text for word in critical_words)
        if critical and flow_kind == "flexible":
            warnings.append("critical_business_should_be_converted_to_fixed_template_before_production_use")
        if critical and human_count == 0:
            blockers.append("critical_business_requires_preset_human_approval")
        if flow_kind == "fixed" and human_count == 0:
            warnings.append("fixed_flow_without_human_approval_should_be_reviewed")
        score = 100 - len(blockers) * 25 - len(warnings) * 8
        return {
            "valid": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "score": max(0, score),
            "summary": {
                "flow_kind": flow_kind,
                "node_count": len(nodes),
                "human_approval_count": human_count,
                "condition_count": condition_count,
                "critical_business_detected": critical,
            },
            "advice": "If blockers exist, ask the AI to revise the design before running or converting it to a fixed template.",
        }

    def _has_design_dependency_cycle(self, graph: Dict[str, List[str]]) -> bool:
        visited = set()
        visiting = set()

        def visit(node_id: str) -> bool:
            if node_id in visiting:
                return True
            if node_id in visited:
                return False
            visiting.add(node_id)
            for dependency in graph.get(node_id, []):
                if dependency in graph and visit(dependency):
                    return True
            visiting.remove(node_id)
            visited.add(node_id)
            return False

        return any(visit(node_id) for node_id in graph)

    def _template_definition_from_design(self, draft: FlowDesignDraft, template_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        steps = []
        for node in draft.nodes:
            node_type = str(node.get("type") or "auto")
            step = {
                "step_id": str(node.get("node_id") or normalize_id(str(node.get("name") or "step"), "step")),
                "type": "human_approval" if node_type == "human_approval" else node_type,
                "name": str(node.get("name") or node.get("node_id") or "step"),
            }
            if step["type"] == "auto":
                step["service_ref"] = str(node.get("service_ref") or node.get("l2_engine_ref") or "L2.generic.execute")
            elif step["type"] == "condition":
                step["condition_ref"] = str(node.get("condition_ref") or "manual_condition_ref_required")
            elif step["type"] == "human_approval":
                step["approval_position"] = str(node.get("approval_position") or "template_owner_unassigned")
            elif step["type"] == "human_notify":
                step["notify_position"] = str(node.get("notify_position") or "template_owner_unassigned")
            for field_name in ("depends_on", "branches", "max_retries", "failure_policy", "timeout_seconds", "timeout_policy"):
                if field_name in node:
                    step[field_name] = deep_copy(node[field_name])
            steps.append(step)
        return {
            "template_id": template_id,
            "name": str(payload.get("template_name") or draft.title),
            "category": str(payload.get("category") or "multi_step_business_process"),
            "owner_position": str(payload.get("owner_position") or "template_owner_unassigned"),
            "applicable_scope": payload.get("applicable_scope") if isinstance(payload.get("applicable_scope"), dict) else {"fixed_flow": True, "source": "flow_design_conversion"},
            "version_policy": {"new_start": "latest_published", "in_flight": "keep_original_version"},
            "rejection_policy": payload.get("rejection_policy") if isinstance(payload.get("rejection_policy"), dict) else {"default": "return_previous_step_or_end_by_template"},
            "policy_file_refs": payload.get("policy_file_refs") if isinstance(payload.get("policy_file_refs"), list) else [],
            "steps": steps,
        }

    def _route(self, text: str, intent_result: Dict[str, Any]) -> Dict[str, Any]:
        explicit_template = intent_result.get("candidate_template_id")
        task_type = str(intent_result.get("task_type") or "")
        if explicit_template:
            return {"route_type": "fixed_template", "template_id": explicit_template, "reason": "Intent analysis provided a fixed template id."}
        approval_words = ["approval", "review", "payment", "expense", "seal", "sign"]
        approval_negated = any(phrase in text.lower() for phrase in ["no approval", "without approval"])
        approval_triggered = any(word in text for word in approval_words) and not approval_negated
        if task_type == "execution" and not approval_triggered:
            return {"route_type": "dynamic_execution", "reason": "Intent is execution and no approval keyword was triggered."}
        table = [
            ("monthly_commission_accrual", ["commission", "accrual"]),
            ("procurement_plan_compare_contract", ["procurement plan", "compare price", "contract"]),
            ("procurement_order_review", ["procurement order"]),
            ("supplier_payment_approval", ["supplier payment", "payment request", "reconciliation"]),
            ("marketing_content_release_review", ["marketing", "promotion", "publish"]),
            ("attendance_exception_review", ["attendance", "clock-in", "exception"]),
            ("invoice_after_payment_followup", ["invoice after payment", "invoice"]),
        ]
        for template_id, words in table:
            if any(word in text for word in words):
                return {"route_type": "fixed_template", "template_id": template_id, "reason": "Matched fixed-flow template keywords."}
        if task_type == "approval" or approval_triggered:
            return {
                "route_type": "fixed_template_missing",
                "reason": "审批类事项必须匹配确定制度和固定模板；当前未命中固定模板，转真人例外定夺。",
            }
        return {"route_type": "dynamic_execution", "reason": "Execution task can be dynamically assembled by L2."}

    def _load_fixed_template_plan(self, instance: FlowInstance, template_id: str) -> None:
        template = self.template_client.retrieve(template_id, instance.trace_id)
        instance.template_id = template["template_id"]
        instance.template_version = template["version"]
        definition = template["definition"]
        instance.artifacts["template_snapshot"] = {
            "template_id": template["template_id"],
            "version": template["version"],
            "name": template["name"],
            "status": template.get("status"),
            "category": template.get("category"),
        }
        instance.artifacts["template_definition_summary"] = {
            "owner_position": definition.get("owner_position"),
            "applicable_scope": deep_copy(definition.get("applicable_scope") or {}),
            "version_policy": deep_copy(definition.get("version_policy") or {}),
            "rejection_policy": deep_copy(definition.get("rejection_policy") or {}),
            "policy_file_refs": deep_copy(definition.get("policy_file_refs") or []),
        }
        instance.artifacts["rejection_policy"] = deep_copy(definition.get("rejection_policy") or {"default": "end"})
        nodes: List[ExecutionNode] = []
        previous_node_id = ""
        for index, step in enumerate(definition.get("steps") or [], 1):
            step_type = str(step.get("type") or "auto")
            node_id = str(step.get("step_id") or f"step_{index}")
            if "depends_on" in step:
                default_depends_on = list(step.get("depends_on") or [])
            else:
                default_depends_on = [previous_node_id] if previous_node_id else []
            if step_type == "human_approval":
                nodes.append(
                    ExecutionNode(
                        node_id=node_id,
                        node_type="human_approval",
                        name=str(step.get("name") or f"鐪熶汉鎷嶆澘 {index}"),
                        approval_position=str(step.get("approval_position") or definition.get("owner_position") or "template_owner_unassigned"),
                        depends_on=default_depends_on,
                        timeout_seconds=int(step.get("timeout_seconds") or 0),
                        timeout_policy=str(step.get("timeout_policy") or "escalate_human"),
                    )
                )
            elif step_type == "human_notify":
                nodes.append(
                    ExecutionNode(
                        node_id=node_id,
                        node_type="human_notify",
                        name=str(step.get("name") or f"鐪熶汉鐭ヤ細 {index}"),
                        notify_position=str(step.get("notify_position") or definition.get("owner_position") or "template_owner_unassigned"),
                        depends_on=default_depends_on,
                        timeout_seconds=int(step.get("timeout_seconds") or 0),
                        timeout_policy=str(step.get("timeout_policy") or "escalate_human"),
                    )
                )
            elif step_type == "condition":
                nodes.append(
                    ExecutionNode(
                        node_id=node_id,
                        node_type="condition",
                        name=str(step.get("name") or f"鏉′欢鍒ゆ柇 {index}"),
                        condition_ref=str(step.get("condition_ref") or ""),
                        branches=deep_copy(step.get("branches") or {}),
                        service_ref="L2.rule_engine.procurement_compare",
                        depends_on=default_depends_on,
                        max_retries=int(step.get("max_retries") or 0),
                        failure_policy=str(step.get("failure_policy") or "fail"),
                        timeout_seconds=int(step.get("timeout_seconds") or 0),
                        timeout_policy=str(step.get("timeout_policy") or "escalate_human"),
                    )
                )
            else:
                nodes.append(
                    ExecutionNode(
                        node_id=node_id,
                        node_type="auto_task",
                        name=str(step.get("name") or f"鑷姩浠诲姟 {index}"),
                        service_ref=str(step.get("service_ref") or step.get("l2_engine_ref") or "L2.generic.execute"),
                        depends_on=default_depends_on,
                        max_retries=int(step.get("max_retries") or 0),
                        failure_policy=str(step.get("failure_policy") or "fail"),
                        timeout_seconds=int(step.get("timeout_seconds") or 0),
                        timeout_policy=str(step.get("timeout_policy") or "escalate_human"),
                    )
                )
            previous_node_id = node_id
        instance.nodes = nodes
        instance.artifacts["execution_plan"] = self._execution_plan(instance, source="fixed_template")
        self._log(instance, "template_locked", f"Locked L1.2 template {template_id} v{instance.template_version}", instance.artifacts["template_snapshot"])

    def _create_dynamic_plan(self, instance: FlowInstance, text: str, intent_result: Optional[Dict[str, Any]] = None) -> None:
        command = intent_result or {}
        capability_ids = [str(item) for item in command.get("capability_ids") or [] if str(item).strip()]
        if capability_ids:
            if command.get("requires_user_confirmation") and not command.get("user_confirmed"):
                raise ValueError("intent_confirmation_required")
            nodes: List[ExecutionNode] = []
            snapshots = []
            node_ids = {capability_id: normalize_id(capability_id, "capability") for capability_id in capability_ids}
            dependencies = self._capability_dependencies(command.get("dependencies"), capability_ids)
            for index, capability_id in enumerate(capability_ids, 1):
                service, definition, registration = self.registry.resolve_capability(capability_id)
                node_id = node_ids[capability_id]
                nodes.append(
                    ExecutionNode(
                        node_id=node_id,
                        node_type="auto_task",
                        name=f"Execute {capability_id}",
                        service_ref=service.service_name,
                        depends_on=[node_ids[parent] for parent in dependencies[capability_id]],
                        max_retries=1,
                        failure_policy="escalate_human",
                        capability_id=definition.capability_id,
                        capability_dictionary_version=definition.dictionary_version,
                        registry_version=registration.registry_version,
                        schema_version=registration.schema_version,
                        service_action=registration.action,
                    )
                )
                snapshots.append(self.registry.capability_snapshot(capability_id))
            instance.nodes = nodes
            instance.artifacts["capability_registry_snapshot"] = snapshots
            instance.artifacts["confirmed_command"] = {
                key: deep_copy(command[key]) for key in (
                    "command_id", "capability_dictionary_version", "capability_ids", "parameters",
                    "dependencies", "risk_level", "requires_user_confirmation", "user_confirmed",
                ) if key in command
            }
            instance.artifacts["execution_plan"] = self._execution_plan(instance, source="capability_selected_execution")
            self._log(instance, "capabilities_frozen", "Capability and registration versions frozen for this instance.", {"capabilities": snapshots})
            return
        if any(word in text.lower() for word in ["wechat", "website", "mail", "multi-channel", "simultaneously"]) or any(word in text for word in ["公众号", "官网", "邮件", "多平台", "同时"]):
            instance.nodes = [
                ExecutionNode("plan", "auto_task", "Create temporary execution plan", service_ref="L2.content.generate", max_retries=1, failure_policy="escalate_human"),
                ExecutionNode("channel_wechat", "auto_task", "Distribute to WeChat channel", service_ref="L2.external.oa_submit", depends_on=["plan"], max_retries=1, failure_policy="escalate_human"),
                ExecutionNode("channel_site", "auto_task", "Distribute to website", service_ref="L2.external.oa_submit", depends_on=["plan"], max_retries=1, failure_policy="escalate_human"),
                ExecutionNode("channel_mail", "auto_task", "Distribute to mail list", service_ref="L2.external.oa_submit", depends_on=["plan"], max_retries=1, failure_policy="escalate_human"),
                ExecutionNode("summary", "auto_task", "Summarize distribution result", service_ref="L2.generic.execute", depends_on=["channel_wechat", "channel_site", "channel_mail"], max_retries=1, failure_policy="escalate_human"),
            ]
            instance.artifacts["parallel_group"] = ["channel_wechat", "channel_site", "channel_mail"]
        else:
            instance.nodes = [
                ExecutionNode("plan", "auto_task", "Create temporary execution plan", service_ref="L2.generic.execute", max_retries=1, failure_policy="escalate_human"),
                ExecutionNode("execute", "auto_task", "Dispatch delegated execution engine", service_ref="L2.generic.execute", depends_on=["plan"], max_retries=1, failure_policy="escalate_human"),
                ExecutionNode("summary", "auto_task", "Summarize execution result", service_ref="L2.generic.execute", depends_on=["execute"], max_retries=1, failure_policy="escalate_human"),
            ]
        instance.artifacts["execution_plan"] = self._execution_plan(instance, source="dynamic_execution")
        self._log(instance, "dynamic_plan_created", "Dynamic execution plan created.", {"node_count": len(instance.nodes)})

    def _capability_dependencies(self, raw_dependencies: Any, capability_ids: List[str]) -> Dict[str, List[str]]:
        """Normalize the intent engine's dependency declaration without re-planning it."""
        dependencies = {capability_id: [] for capability_id in capability_ids}
        if isinstance(raw_dependencies, dict):
            for capability_id, parents in raw_dependencies.items():
                if capability_id not in dependencies:
                    raise ValueError(f"capability_dependency_unknown:{capability_id}")
                parent_ids = parents if isinstance(parents, list) else [parents]
                dependencies[capability_id] = [str(parent) for parent in parent_ids if str(parent)]
        elif isinstance(raw_dependencies, list):
            for edge in raw_dependencies:
                if not isinstance(edge, dict):
                    raise ValueError("capability_dependency_invalid")
                capability_id = str(edge.get("capability_id") or edge.get("to") or "")
                parent_ids = edge.get("depends_on") or edge.get("from") or []
                if capability_id not in dependencies:
                    raise ValueError(f"capability_dependency_unknown:{capability_id}")
                dependencies[capability_id] = parent_ids if isinstance(parent_ids, list) else [str(parent_ids)]
        elif raw_dependencies:
            raise ValueError("capability_dependency_invalid")
        for capability_id, parents in dependencies.items():
            if any(parent not in dependencies for parent in parents) or capability_id in parents:
                raise ValueError(f"capability_dependency_invalid:{capability_id}")
        return dependencies

    def _apply_rejection_policy(self, instance: FlowInstance, node: ExecutionNode, task: HumanTask, reason: str) -> bool:
        policy = instance.artifacts.get("rejection_policy") if isinstance(instance.artifacts.get("rejection_policy"), dict) else {}
        action = str(policy.get("default") or policy.get("on_reject") or "end")
        target_step_id = str(policy.get("return_to_step_id") or policy.get("target_step_id") or "")
        if action in {"end", "terminate", "fail"}:
            instance.artifacts.setdefault("rejection_history", []).append(
                {
                    "node_id": node.node_id,
                    "task_id": task.task_id,
                    "action": "end",
                    "reason": reason,
                    "decided_at": task.decided_at,
                }
            )
            return False
        node_ids = [item.node_id for item in instance.nodes]
        if action in {"return_to_step", "return_to_previous_step", "return_previous_step", "return_previous_step_or_end_by_template"}:
            if target_step_id and target_step_id in node_ids:
                target_index = node_ids.index(target_step_id)
            else:
                current_index = node_ids.index(node.node_id)
                target_index = current_index - 1
            if target_index < 0:
                instance.artifacts.setdefault("rejection_history", []).append(
                    {
                        "node_id": node.node_id,
                        "task_id": task.task_id,
                        "action": "end_no_previous_step",
                        "reason": reason,
                        "decided_at": task.decided_at,
                    }
                )
                return False
            reset_node_ids = self._downstream_node_ids(instance, instance.nodes[target_index].node_id)
            for reset_node in instance.nodes:
                if reset_node.node_id not in reset_node_ids:
                    continue
                self._transition_node(reset_node, "pending")
                reset_node.output = {
                    "from_node_id": node.node_id,
                    "reason": reason,
                    "decided_at": task.decided_at,
                }
            target_node = instance.nodes[target_index]
            self._transition_instance(instance, "in_progress")
            instance.current_nodes = [target_node.node_id]
            instance.artifacts.setdefault("rejection_history", []).append(
                {
                    "node_id": node.node_id,
                    "task_id": task.task_id,
                    "action": "return_to_step",
                    "target_step_id": target_node.node_id,
                    "reason": reason,
                    "decided_at": task.decided_at,
                }
            )
            self._log(instance, "rejection_policy_applied", f"Returned to {target_node.name}.", instance.artifacts["rejection_history"][-1])
            return True
        instance.artifacts.setdefault("rejection_history", []).append(
            {
                "node_id": node.node_id,
                "task_id": task.task_id,
                "action": f"unsupported_policy:{action}",
                "reason": reason,
                "decided_at": task.decided_at,
            }
        )
        return False

    def _downstream_node_ids(self, instance: FlowInstance, root_node_id: str) -> set[str]:
        """Return a node and every dependency descendant; independent parallel work remains intact."""
        descendants = {root_node_id}
        changed = True
        while changed:
            changed = False
            for candidate in instance.nodes:
                if candidate.node_id in descendants:
                    continue
                if any(parent in descendants for parent in candidate.depends_on):
                    descendants.add(candidate.node_id)
                    changed = True
        return descendants

    def _run_until_pause_or_done(self, instance: FlowInstance) -> None:
        self._transition_instance(instance, "in_progress")
        while True:
            pending = [node for node in instance.nodes if node.status == "pending"]
            if not pending:
                break
            ready = [node for node in pending if self._dependencies_completed(instance, node)]
            if not ready:
                self._transition_instance(instance, "failed")
                instance.current_nodes = []
                instance.artifacts["final_result"] = "No runnable node found. The execution plan may contain missing or circular dependencies."
                self._log(instance, "dependency_blocked", instance.artifacts["final_result"], {"pending_nodes": [node.node_id for node in pending]})
                return
            instance.current_nodes = [node.node_id for node in ready]
            human_ready = [node for node in ready if node.node_type == "human_approval"]
            if human_ready:
                for node in human_ready:
                    self._transition_node(node, "in_progress")
                    self._pause_for_human(instance, node, mode="approve")
                instance.current_nodes = [node.node_id for node in human_ready]
                return
            for node in ready:
                self._transition_node(node, "in_progress")
                if not node.started_at:
                    node.started_at = now_iso()
                if node.node_type == "human_notify":
                    self._notify_human(instance, node)
                    self._transition_node(node, "completed")
                    node.completed_at = now_iso()
                    continue
                self._execute_auto_node(instance, node)
                if node.status == "failed":
                    if self._handle_node_failure(instance, node):
                        if instance.status == "waiting_human":
                            instance.current_nodes = [node.node_id]
                            return
                        continue
                    self._transition_instance(instance, "failed")
                    instance.current_nodes = [node.node_id]
                    instance.artifacts["final_result"] = node.output.get("summary") or "Auto node failed."
                    return
        self._transition_instance(instance, "completed")
        instance.current_nodes = []
        instance.artifacts["final_result"] = "Flow instance completed; result is ready for requester."
        self._log(instance, "completed", "Flow instance completed.", {"instance_id": instance.instance_id})

    def _dependencies_completed(self, instance: FlowInstance, node: ExecutionNode) -> bool:
        if not node.depends_on:
            return True
        completed = {item.node_id for item in instance.nodes if item.status in {"completed", "skipped"}}
        return all(dep in completed for dep in node.depends_on)

    def _handle_node_failure(self, instance: FlowInstance, node: ExecutionNode) -> bool:
        if node.retry_count < node.max_retries:
            node.retry_count += 1
            self._transition_node(node, "pending")
            self._log(instance, "node_retry_scheduled", f"Retry {node.retry_count}/{node.max_retries}: {node.name}", {"node_id": node.node_id})
            return True
        if node.failure_policy in {"escalate_human", "exception_review"}:
            self._transition_instance(instance, "waiting_human")
            instance.artifacts["exception"] = node.output.get("summary") or f"Node failed: {node.name}"
            self._create_exception_task(instance, instance.artifacts["exception"])
            self._log(instance, "node_escalated_to_human", node.name, {"node_id": node.node_id, "failure_policy": node.failure_policy})
            return True
        return False

    def _execute_auto_node(self, instance: FlowInstance, node: ExecutionNode) -> None:
        try:
            service = self.registry.resolve(node.service_ref or "L2.generic.execute")
            node.dispatch_attempt += 1
            dispatch = {
                "task_id": instance.instance_id,
                "subtask_id": f"{instance.instance_id}:{node.node_id}:{node.dispatch_attempt}",
                "trace_id": instance.trace_id,
                "requester_id": instance.requester_id,
                "node_name": node.name,
                "task": node.name,
                "service_ref": node.service_ref,
                "service_code": node.service_ref,
                "action": node.service_action or service.request_type,
                "capability_id": node.capability_id,
                "capability_dictionary_version": node.capability_dictionary_version,
                "registry_version": node.registry_version,
                "schema_version": node.schema_version,
            }
            dispatch_task = DispatchTask(
                task_id=instance.instance_id,
                subtask_id=dispatch["subtask_id"],
                node_id=node.node_id,
                target_engine_id=service.engine_id,
                target_engine_name=service.engine_name,
                service_name=service.service_name,
                request_type=service.request_type,
                status="accepted",
                payload=deep_copy(dispatch),
            )
            instance.dispatch_tasks.append(dispatch_task)
            self._log(instance, "subtask_dispatched", node.name, asdict(dispatch_task))
            result = self.executor.execute(service, dispatch)
            node.output = result
            self._transition_node(node, "completed" if result.get("ok") else "failed")
            if node.status == "completed":
                node.completed_at = now_iso()
            if node.status == "completed" and node.node_type == "condition":
                self._apply_condition_branch(instance, node, result)
            self._transition_dispatch_task(dispatch_task, "completed" if result.get("ok") else "failed")
            dispatch_task.result = deep_copy(result)
            dispatch_task.updated_at = now_iso()
            self._log(instance, "subtask_completed", node.name, result)
        except ValueError as exc:
            self._transition_node(node, "failed")
            node.output = {"ok": False, "summary": str(exc)}
            self._log(instance, "subtask_failed", node.name, node.output)

    def _apply_condition_branch(self, instance: FlowInstance, node: ExecutionNode, result: Dict[str, Any]) -> None:
        if not node.branches:
            return
        branch_name = str(result.get("branch") or result.get("condition_outcome") or "default")
        branch = node.branches.get(branch_name) or node.branches.get("default")
        if not isinstance(branch, dict):
            self._transition_instance(instance, "failed")
            self._transition_node(node, "failed")
            node.output["summary"] = f"Condition branch not configured: {branch_name}"
            self._log(instance, "condition_branch_missing", node.name, {"branch": branch_name})
            return
        selected_activate = {str(target_id) for target_id in branch.get("activate") or []}
        selected_skip = {str(target_id) for target_id in branch.get("skip") or []}
        unselected_activate = {
            str(target_id)
            for name, candidate in node.branches.items()
            if name != branch_name and isinstance(candidate, dict)
            for target_id in candidate.get("activate") or []
        }
        skipped = []
        for target_id in selected_skip | unselected_activate:
            target = self._node(instance, str(target_id))
            if target.status == "pending":
                self._transition_node(target, "skipped")
                target.output = {
                    "skipped_by_condition": node.node_id,
                    "branch": branch_name,
                    "reason": "selected_branch_skip" if target_id in selected_skip else "unselected_branch",
                }
                skipped.append(target.node_id)
        node.output["selected_branch"] = branch_name
        node.output["activated_nodes"] = sorted(selected_activate)
        node.output["skipped_nodes"] = skipped
        self._log(instance, "condition_branch_selected", node.name, {"branch": branch_name, "activated_nodes": sorted(selected_activate), "skipped_nodes": skipped})

    def _pause_for_human(self, instance: FlowInstance, node: ExecutionNode, mode: str) -> None:
        if not node.started_at:
            node.started_at = now_iso()
        try:
            person = self.organization.resolve(node.approval_position)
        except ValueError as exc:
            self._transition_instance(instance, "waiting_human")
            instance.artifacts["exception"] = str(exc)
            self._create_exception_task(instance, str(exc))
            return
        task = HumanTask(
            task_id=f"human_{uuid.uuid4().hex[:10]}",
            node_id=node.node_id,
            mode=mode,
            position_id=node.approval_position,
            assignee_id=person["person_id"],
            assignee_name=person["name"],
            title=f"Pending approval: {node.name}",
            summary="Flow reached a preset human approval node. Approve or reject with a reason.",
        )
        instance.human_tasks.append(task)
        self._transition_node(node, "waiting_human")
        self._transition_instance(instance, "waiting_human")
        self._deliver_human_task(instance, task)
        self._log(instance, "human_task_created", task.title, asdict(task))

    def _notify_human(self, instance: FlowInstance, node: ExecutionNode) -> None:
        position = node.notify_position or node.approval_position or "template_owner_unassigned"
        person = self.organization.resolve(position)
        task = HumanTask(
            task_id=f"notify_{uuid.uuid4().hex[:10]}",
            node_id=node.node_id,
            mode="notify",
            position_id=position,
            assignee_id=person["person_id"],
            assignee_name=person["name"],
            title=f"Notification: {node.name}",
            summary="This node is notification-only and does not block the flow.",
            status="done",
        )
        instance.human_tasks.append(task)
        self._deliver_notification(instance, task)
        self._log(instance, "human_notify_sent", task.title, asdict(task))

    def _create_exception_task(self, instance: FlowInstance, reason: str) -> None:
        person = self.organization.resolve("template_owner_unassigned")
        task = HumanTask(
            task_id=f"exception_{uuid.uuid4().hex[:10]}",
            node_id="exception",
            mode="exception_review",
            position_id="template_owner_unassigned",
            assignee_id=person["person_id"],
            assignee_name=person["name"],
            title="Flow exception pending review",
            summary=reason,
        )
        instance.human_tasks.append(task)
        self._deliver_human_task(instance, task)
        self._log(instance, "exception_task_created", reason, asdict(task))

    def _deliver_human_task(self, instance: FlowInstance, task: HumanTask) -> None:
        self._record_delivery(instance, task, "todo", self.workbench.create_task)

    def _deliver_notification(self, instance: FlowInstance, task: HumanTask) -> None:
        self._record_delivery(instance, task, "notification", self.workbench.send_notification)

    def _record_delivery(
        self,
        instance: FlowInstance,
        task: HumanTask,
        delivery_type: str,
        deliver: Callable[[HumanTask, str], Dict[str, Any]],
    ) -> None:
        try:
            result = deliver(task, instance.trace_id)
            if not isinstance(result, dict):
                result = {"ok": False, "summary": "workbench_gateway_invalid_response"}
        except Exception as exc:
            result = {"ok": False, "summary": f"workbench_gateway_error:{exc}"}
        delivery = {"delivery_id": f"delivery_{uuid.uuid4().hex[:12]}", "task_id": task.task_id, "type": delivery_type, "result": deep_copy(result), "attempts": 1, "max_attempts": 3, "status": "delivered" if result.get("ok") else "pending_retry", "at": now_iso()}
        if not result.get("ok"):
            delivery["next_retry_at"] = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        instance.artifacts.setdefault("workbench_deliveries", []).append(delivery)
        self._log(instance, "workbench_delivery_succeeded" if result.get("ok") else "workbench_delivery_failed", task.title, delivery)

    def retry_workbench_delivery(self, instance_id: str, delivery_id: str) -> Dict[str, Any]:
        instance = self._instance(instance_id)
        delivery = next((item for item in instance.artifacts.get("workbench_deliveries", []) if item.get("delivery_id") == delivery_id), None)
        if not delivery:
            raise ValueError("workbench_delivery_not_found")
        if delivery.get("result", {}).get("ok"):
            return {"delivery_id": delivery_id, "retried": False, "reason": "delivery_already_succeeded"}
        if delivery.get("status") == "dead_letter" or int(delivery.get("attempts") or 0) >= int(delivery.get("max_attempts") or 3):
            delivery["status"] = "dead_letter"
            self._persist()
            return {"delivery_id": delivery_id, "retried": False, "reason": "delivery_attempt_limit_reached"}
        task = next((item for item in instance.human_tasks if item.task_id == delivery.get("task_id")), None)
        if not task:
            raise ValueError("human_task_not_found")
        deliver = self.workbench.create_task if delivery.get("type") == "todo" else self.workbench.send_notification
        try:
            result = deliver(task, instance.trace_id)
            if not isinstance(result, dict):
                result = {"ok": False, "summary": "workbench_gateway_invalid_response"}
        except Exception as exc:
            result = {"ok": False, "summary": f"workbench_gateway_error:{exc}"}
        delivery["result"] = deep_copy(result)
        delivery["attempts"] = int(delivery.get("attempts") or 0) + 1
        delivery["retried_at"] = now_iso()
        delivery["status"] = "delivered" if result.get("ok") else ("dead_letter" if delivery["attempts"] >= int(delivery.get("max_attempts") or 3) else "pending_retry")
        if delivery["status"] == "pending_retry":
            delay_seconds = min(300, 5 * (2 ** (delivery["attempts"] - 1)))
            delivery["next_retry_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
        else:
            delivery.pop("next_retry_at", None)
        self._log(instance, "workbench_delivery_retry_succeeded" if result.get("ok") else "workbench_delivery_retry_failed", task.title, deep_copy(delivery))
        self._persist()
        return {"delivery_id": delivery_id, "retried": True, "result": deep_copy(result), "attempts": delivery["attempts"]}

    def scan_delivery_retries(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        limit = min(100, max(1, int(payload.get("limit") or 20)))
        now = self._parse_time(str(payload.get("now") or now_iso()))
        attempted = []
        for instance in self.instances.values():
            for delivery in instance.artifacts.get("workbench_deliveries", []):
                if len(attempted) >= limit:
                    break
                if delivery.get("status") != "pending_retry":
                    continue
                next_retry_at = str(delivery.get("next_retry_at") or "")
                if next_retry_at and self._parse_time(next_retry_at) > now:
                    continue
                result = self.retry_workbench_delivery(instance.instance_id, str(delivery["delivery_id"]))
                attempted.append({"instance_id": instance.instance_id, **result})
            if len(attempted) >= limit:
                break
        return {"scanned_at": now.isoformat(), "attempted": attempted, "count": len(attempted)}

    def _parse_time(self, value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid_timeout_scan_time") from exc
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _log(self, instance: FlowInstance, event: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        sequence = max((int(item.get("sequence") or 0) for item in instance.audit_log), default=0) + 1
        instance.audit_log.append({"event_id": f"{instance.instance_id}:event:{sequence}", "sequence": sequence, "at": now_iso(), "event": event, "message": message, "data": deep_copy(data or {})})
        instance.updated_at = now_iso()

    def _node(self, instance: FlowInstance, node_id: str) -> ExecutionNode:
        for node in instance.nodes:
            if node.node_id == node_id:
                return node
        raise ValueError("node_not_found")

    def _instance(self, instance_id: str) -> FlowInstance:
        if instance_id not in self.instances:
            raise ValueError("instance_not_found")
        return self.instances[instance_id]

    def _persist(self) -> None:
        for instance in self.instances.values():
            self._assert_instance_invariants(instance)
        self.repository.save_all(self.instances, self.design_drafts)

    def _transition(self, subject: Any, target: str, transitions: Dict[str, set[str]], subject_name: str) -> None:
        current = str(subject.status)
        if current == target:
            return
        if target not in transitions.get(current, set()):
            raise ValueError(f"invalid_{subject_name}_transition:{current}_to_{target}")
        subject.status = target

    def _transition_instance(self, instance: FlowInstance, target: str) -> None:
        self._transition(instance, target, INSTANCE_TRANSITIONS, "instance")

    def _transition_node(self, node: ExecutionNode, target: str) -> None:
        self._transition(node, target, NODE_TRANSITIONS, "node")

    def _transition_human_task(self, task: HumanTask, target: str) -> None:
        self._transition(task, target, HUMAN_TASK_TRANSITIONS, "human_task")

    def _transition_dispatch_task(self, task: DispatchTask, target: str) -> None:
        self._transition(task, target, DISPATCH_TASK_TRANSITIONS, "dispatch_task")

    def _assert_instance_invariants(self, instance: FlowInstance) -> None:
        if instance.status not in INSTANCE_TRANSITIONS:
            raise ValueError(f"invalid_instance_status:{instance.status}")
        for node in instance.nodes:
            if node.status not in NODE_TRANSITIONS:
                raise ValueError(f"invalid_node_status:{node.node_id}:{node.status}")
        for task in instance.human_tasks:
            if task.status not in HUMAN_TASK_TRANSITIONS:
                raise ValueError(f"invalid_human_task_status:{task.task_id}:{task.status}")
        for task in instance.dispatch_tasks:
            if task.status not in DISPATCH_TASK_TRANSITIONS:
                raise ValueError(f"invalid_dispatch_task_status:{task.subtask_id}:{task.status}")
        pending_human = [task for task in instance.human_tasks if task.status == "pending"]
        if instance.status == "waiting_human" and not pending_human:
            raise ValueError("waiting_human_instance_requires_pending_task")
        if instance.status in {"completed", "failed"} and pending_human:
            raise ValueError("terminal_instance_cannot_have_pending_human_task")

    def _execution_plan(self, instance: FlowInstance, source: str) -> Dict[str, Any]:
        return {
            "source": source,
            "instance_id": instance.instance_id,
            "template_id": instance.template_id,
            "template_version": instance.template_version,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "node_type": node.node_type,
                    "name": node.name,
                    "service_ref": node.service_ref,
                    "service_action": node.service_action,
                    "condition_ref": node.condition_ref,
                    "branches": deep_copy(node.branches),
                    "approval_position": node.approval_position,
                    "notify_position": node.notify_position,
                    "depends_on": list(node.depends_on),
                    "max_retries": node.max_retries,
                    "failure_policy": node.failure_policy,
                    "timeout_seconds": node.timeout_seconds,
                    "timeout_policy": node.timeout_policy,
                    "capability_id": node.capability_id,
                    "capability_dictionary_version": node.capability_dictionary_version,
                    "registry_version": node.registry_version,
                    "schema_version": node.schema_version,
                    "started_at": node.started_at,
                    "completed_at": node.completed_at,
                }
                for node in instance.nodes
            ],
            "generated_at": now_iso(),
        }

    def _public_instance(self, instance: FlowInstance) -> Dict[str, Any]:
        return {
            "instance_id": instance.instance_id,
            "trace_id": instance.trace_id,
            "requester_id": instance.requester_id,
            "scope_id": instance.scope_id,
            "request_text": instance.request_text,
            "route_type": instance.route_type,
            "status": instance.status,
            "platform_status": PLATFORM_STATUS_MAP.get(instance.status, instance.status),
            "template_id": instance.template_id,
            "template_version": instance.template_version,
            "current_step": self._current_step_text(instance),
            "current_nodes": list(instance.current_nodes),
            "nodes": [asdict(item) for item in instance.nodes],
            "dispatch_tasks": [asdict(item) for item in instance.dispatch_tasks],
            "human_tasks": [asdict(item) for item in instance.human_tasks],
            "artifacts": deep_copy(instance.artifacts),
            "audit_log": deep_copy(instance.audit_log[-20:]),
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }

    def _design(self, design_id: str) -> FlowDesignDraft:
        if design_id not in self.design_drafts:
            raise ValueError("design_not_found")
        return self.design_drafts[design_id]

    def _public_design(self, draft: FlowDesignDraft) -> Dict[str, Any]:
        return {
            "design_id": draft.design_id,
            "requester_id": draft.requester_id,
            "source_text": draft.source_text,
            "flow_kind": draft.flow_kind,
            "status": draft.status,
            "title": draft.title,
            "nodes": deep_copy(draft.nodes),
            "validation": deep_copy(draft.validation),
            "candidate_template_id": draft.candidate_template_id,
            "created_at": draft.created_at,
            "updated_at": draft.updated_at,
            "ui_note": "Fixed and flexible flows can share this design surface. L2 owns design and validation; L1.2 only stores confirmed fixed-template drafts.",
        }

    def _current_step_text(self, instance: FlowInstance) -> str:
        if instance.status == "completed":
            return "流程已完成，结果可返回发起人。"
        if instance.status == "failed":
            return f"Flow ended: {instance.artifacts.get('final_result') or instance.artifacts.get('exception') or 'failed'}"
        if instance.status == "waiting_human":
            pending = [item for item in instance.human_tasks if item.status == "pending"]
            if pending:
                task = pending[-1]
                return f"等待 {task.assignee_name} 处理：{task.title}"
            return "流程暂停，等待真人处理。"
        if instance.current_nodes:
            node = self._node(instance, instance.current_nodes[0])
            return f"Running: {node.name}"
        return "Flow accepted and preparing to run."

    def _error(self, trace_id: str, service_name: str, code: str) -> Dict[str, Any]:
        messages = {
            "service_not_registered": "Service is not registered in L2.",
            "requester_id_required": "Flow start requires requester_id.",
            "instance_not_found": "Flow instance was not found.",
            "human_task_not_found": "Human task was not found.",
            "human_task_already_decided": "Human task has already been decided.",
            "decision_must_be_approved_rejected_modified_or_answered": "Decision must be approved, rejected, modified, or answered.",
            "dispatch_status_not_standard": "Dispatch status must use a standard task status.",
            "request_text_required": "Flow design requires request_text.",
            "design_not_found": "Flow design draft was not found.",
            "design_nodes_must_be_list": "Flow design nodes must be a list.",
            "design_has_validation_blockers": "Flow design has validation blockers and cannot be converted.",
            "human_confirmation_required": "Converting a design to a fixed-template draft requires human confirmation.",
        }
        return {
            "ok": False,
            "trace_id": trace_id,
            "service_version": SERVICE_VERSION,
            "service_name": service_name,
            "error": {"code": code, "message": messages.get(code, code)},
        }


def build_demo_engine(path: Optional[Path] = None) -> FlowExecutionEngine:
    repo = JsonInstanceRepository(path) if path else InMemoryInstanceRepository()
    return FlowExecutionEngine(repository=repo)
