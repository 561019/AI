from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from adapters.mock_account_gateway import MockAccountGateway
from adapters.mock_archive_service import MockArchiveService
from adapters.mock_permission_management import MockPermissionManagement
from adapters.mock_project_repository import MockProjectRepository
from adapters.mock_security_compliance import MockSecurityCompliance
from core.capability_router import CapabilityRouter
from core.errors import BusinessError
from core.governance import ActionGovernanceGuard
from core.message_contract import MessageContractValidator
from core.message_schema import InternalMessage
from core.source_admission import SourceAdmission
from core.standard_reply import accepted, failed, public_reply, with_governance
from core.trace_context import new_trace_id
from services.service_archive import ProjectArchiveService
from services.service_async_task import ProjectAsyncTaskService
from services.service_authorization import ProjectArchiveAuthorizationService
from services.service_closure import ProjectClosureService
from services.service_grade import ProjectGradeService
from services.service_lifecycle import ProjectLifecycleService
from services.service_member_roster import ProjectMemberRosterService
from services.service_query import ProjectQueryService
from services.service_register import ProjectRegistrationService
from services.service_trace import ProjectTraceService


ROOT = Path(__file__).resolve().parent

repository = MockProjectRepository(ROOT / "project_management.db")
account_gateway = MockAccountGateway()
permission_management = MockPermissionManagement()
security_compliance = MockSecurityCompliance()
archive_mock = MockArchiveService()

registration_service = ProjectRegistrationService(repository)
lifecycle_service = ProjectLifecycleService(repository)
grade_service = ProjectGradeService(repository)
member_service = ProjectMemberRosterService(repository, account_gateway, permission_management)
closure_service = ProjectClosureService(repository, permission_management, archive_mock)
archive_service = ProjectArchiveService(repository)
authorization_service = ProjectArchiveAuthorizationService(repository, account_gateway, permission_management)
query_service = ProjectQueryService(repository)
trace_service = ProjectTraceService(repository)
async_task_service = ProjectAsyncTaskService(repository)

governance_guard = ActionGovernanceGuard(
    repository,
    account_gateway,
    permission_management,
    security_compliance,
)
source_admission = SourceAdmission()
message_contract = MessageContractValidator()
capability_router = CapabilityRouter()

app = FastAPI(
    title="项目管理引擎 API",
    version="0.6.0-stage6",
    description=(
        "项目管理引擎平台规范补强版：档位转换、成员变更、"
        "来源路由矩阵、动作级权限、安全合规和异步回调。"
        "当前仍属于 Mock 独立功能验证和平台联调准备。"
    ),
)


class RegisterProjectRequest(BaseModel):
    project_name: str
    project_category: str
    project_grade: str = "SIMPLE"
    budget_attribute: str
    initiator_person_id: str
    description: Optional[str] = None
    trace_id: Optional[str] = None
    idempotency_key: str


class ApprovalResultRequest(BaseModel):
    approval_result: str
    approval_basis_ref: Optional[str] = None
    approval_comment: Optional[str] = None
    operator_person_id: str
    workflow_instance_id: Optional[str] = None
    task_id: Optional[str] = None
    message_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    trace_id: Optional[str] = None
    idempotency_key: str


class GradeChangeRequest(BaseModel):
    target_grade: str
    change_reason: Optional[str] = None
    operator_person_id: str
    workflow_instance_id: Optional[str] = None
    node_id: Optional[str] = None
    trace_id: Optional[str] = None
    idempotency_key: str


class GradeChangeResultRequest(BaseModel):
    target_grade: str
    change_result: str
    change_basis_ref: str
    change_reason: Optional[str] = None
    operator_person_id: str
    workflow_instance_id: Optional[str] = None
    task_id: Optional[str] = None
    message_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    trace_id: Optional[str] = None
    idempotency_key: str


class AddMemberRequest(BaseModel):
    person_id: str
    position_code: str
    project_role: str
    permission_scope: Dict[str, Any] = Field(default_factory=dict)
    allowed_actions: List[str] = Field(default_factory=lambda: ["project.read"])
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    authorization_basis_ref: str
    operator_person_id: str
    trace_id: Optional[str] = None
    idempotency_key: str


class UpdateMemberRequest(BaseModel):
    position_code: Optional[str] = None
    project_role: Optional[str] = None
    permission_scope: Optional[Dict[str, Any]] = None
    allowed_actions: Optional[List[str]] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    change_basis_ref: str
    change_reason: Optional[str] = None
    operator_person_id: str
    trace_id: Optional[str] = None
    idempotency_key: str


class RemoveMemberRequest(BaseModel):
    revocation_basis_ref: str
    exit_reason: Optional[str] = None
    operator_person_id: str
    trace_id: Optional[str] = None
    idempotency_key: str


class ClosureRequest(BaseModel):
    closure_basis_ref: str
    closure_reason: Optional[str] = None
    archive_mode: str = "SUCCESS"
    archive_resources: List[Dict[str, Any]] = Field(default_factory=list)
    operator_person_id: str
    workflow_instance_id: Optional[str] = None
    trace_id: Optional[str] = None
    idempotency_key: str


class ArchiveAuthorizationRequest(BaseModel):
    applicant_person_id: str
    allowed_actions: List[str] = Field(default_factory=lambda: ["project.archive.catalog.read"])
    allowed_scope: Dict[str, Any] = Field(default_factory=dict)
    authorization_basis_ref: str
    valid_from: Optional[str] = None
    valid_until: str
    operator_person_id: str
    trace_id: Optional[str] = None
    idempotency_key: str


class TaskProgressRequest(BaseModel):
    progress_percent: int
    status_message: str
    operator_person_id: str
    message_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    trace_id: Optional[str] = None
    idempotency_key: str


class TaskFinalCallbackRequest(BaseModel):
    callback_status: str
    result: Dict[str, Any] = Field(default_factory=dict)
    operator_person_id: str
    message_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    trace_id: Optional[str] = None
    idempotency_key: str


def response(reply):
    return JSONResponse(
        status_code=int(reply.get("_http_status", 200)),
        content=public_reply(reply),
    )


def error_reply(exc, trace_id, governance=None):
    reply = failed(
        trace_id=trace_id,
        code=exc.code,
        message=exc.message,
        retryable=exc.retryable,
        http_status=exc.http_status,
    )
    return with_governance(reply, governance) if governance else reply


def governed_call(*, actor_person_id, action, trace_id, handler, project_id=None, resource_scope=None, payload=None, basis_ref=None):
    governance = governance_guard.authorize(
        actor_person_id=actor_person_id,
        action=action,
        trace_id=trace_id,
        resource_scope=resource_scope or ({"project_id": project_id} if project_id else {}),
        payload=payload or {},
        project_id=project_id,
        basis_ref=basis_ref,
    )
    try:
        reply = handler()
    except BusinessError as exc:
        reply = error_reply(exc, trace_id, governance)
        return reply
    return with_governance(reply, governance)


def local_message_id(prefix):
    return prefix + "_" + uuid4().hex[:16].upper()


def attach_async_task(reply, *, action, trace_id, idempotency_key, request_payload, project_id=None, workflow_instance_id=None, node_id=None, source_message_id=None, task_id=None):
    task_reply = async_task_service.accept(
        action=action,
        trace_id=trace_id,
        idempotency_key="TASK::" + idempotency_key,
        request_payload=request_payload,
        project_id=project_id,
        workflow_instance_id=workflow_instance_id,
        node_id=node_id,
        source_message_id=source_message_id,
        task_id=task_id,
    )
    result = dict(reply)
    data = dict(result.get("data") or {})
    data.update(task_reply["data"])
    result["data"] = data
    result["reply_type"] = "accepted"
    result["message"] = task_reply["message"]
    result["_http_status"] = 202
    return result


@app.get("/")
def service_root():
    return {
        "service": "project_management_engine",
        "name": "项目管理引擎",
        "version": "0.6.0-stage6",
        "status": "running",
        "mock_mode": True,
        "strengthened_items": [
            "project_grade_change",
            "member_update",
            "source_route_capability_matrix",
            "action_level_permission",
            "security_compliance_audit_ref",
            "accepted_progress_final_callback",
            "complete_integration_documents",
        ],
        "links": {
            "health": "/health",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "projects": "/api/v1/projects",
        },
        "boundary": "Mock 独立功能验证和平台联调准备，不代表正式联合验收或生产上线。",
    }


@app.get("/favicon.ico")
def favicon():
    from fastapi.responses import Response
    return Response(status_code=204)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "project_management_engine",
        "version": "0.6.0-stage6",
        "mock_mode": True,
        "protocol_version": "1.0",
        "capability_dictionary_version": "2026.07.v06",
        "registry_version": "registry_2026.07.v06",
    }


@app.post("/api/v1/projects/register")
def register_project(request: RegisterProjectRequest):
    trace_id = request.trace_id or new_trace_id()
    grade = request.project_grade.upper()
    action = "project.register.major" if grade == "MAJOR" else "project.register.simple"
    payload = request.model_dump(exclude={"trace_id", "idempotency_key"})
    try:
        reply = governed_call(
            actor_person_id=request.initiator_person_id,
            action=action,
            trace_id=trace_id,
            payload=payload,
            resource_scope={"resource_type": "project_registry"},
            handler=lambda: registration_service.register(
                payload=payload,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                operator_person_id=request.initiator_person_id,
            ),
        )
        if reply["reply_type"] == "accepted" and reply.get("error") is None:
            project_id = reply["data"]["project"]["project_id"]
            reply = attach_async_task(
                reply,
                action="project.approval.wait",
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                request_payload=payload,
                project_id=project_id,
                source_message_id=local_message_id("MSG_LOCAL_MAJOR_REGISTER"),
            )
        return response(reply)
    except BusinessError as exc:
        return response(error_reply(exc, trace_id))


@app.post("/api/v1/projects/{project_id}/approval-result")
def record_approval_result(project_id: str, request: ApprovalResultRequest):
    trace_id = request.trace_id or new_trace_id()
    payload = request.model_dump(exclude={"trace_id", "idempotency_key", "operator_person_id", "workflow_instance_id", "task_id", "message_id", "parent_message_id"})
    try:
        reply = governed_call(
            actor_person_id=request.operator_person_id,
            action="project.approval.result.record",
            trace_id=trace_id,
            project_id=project_id,
            payload=payload,
            basis_ref=request.approval_basis_ref,
            handler=lambda: lifecycle_service.record_approval_result(
                project_id=project_id,
                payload=payload,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                operator_person_id=request.operator_person_id,
                workflow_instance_id=request.workflow_instance_id,
            ),
        )
        if request.task_id and reply.get("error") is None:
            async_task_service.complete(
                task_id=request.task_id,
                callback_status="SUCCESS",
                result=public_reply(reply),
                trace_id=trace_id,
                message_id=request.message_id,
                parent_message_id=request.parent_message_id,
            )
        return response(reply)
    except BusinessError as exc:
        return response(error_reply(exc, trace_id))


@app.post("/api/v1/projects/{project_id}/grade-change-requests")
def request_grade_change(project_id: str, request: GradeChangeRequest):
    trace_id = request.trace_id or new_trace_id()
    payload = request.model_dump(exclude={"trace_id", "idempotency_key", "operator_person_id", "workflow_instance_id", "node_id"})
    try:
        reply = governed_call(
            actor_person_id=request.operator_person_id,
            action="project.grade.change.request",
            trace_id=trace_id,
            project_id=project_id,
            payload=payload,
            handler=lambda: async_task_service.accept(
                action="project.grade.change.request",
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                request_payload=payload,
                project_id=project_id,
                workflow_instance_id=request.workflow_instance_id,
                node_id=request.node_id,
                source_message_id=local_message_id("MSG_LOCAL_GRADE_CHANGE"),
            ) if grade_service.validate_request(project_id=project_id, target_grade=request.target_grade) else None,
        )
        return response(reply)
    except BusinessError as exc:
        return response(error_reply(exc, trace_id))


@app.post("/api/v1/projects/{project_id}/grade-change-result")
def record_grade_change_result(project_id: str, request: GradeChangeResultRequest):
    trace_id = request.trace_id or new_trace_id()
    payload = request.model_dump(exclude={"trace_id", "idempotency_key", "operator_person_id", "workflow_instance_id", "task_id", "message_id", "parent_message_id"})
    try:
        reply = governed_call(
            actor_person_id=request.operator_person_id,
            action="project.grade.change.result.record",
            trace_id=trace_id,
            project_id=project_id,
            payload=payload,
            basis_ref=request.change_basis_ref,
            handler=lambda: grade_service.record_result(
                project_id=project_id,
                payload=payload,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                operator_person_id=request.operator_person_id,
                workflow_instance_id=request.workflow_instance_id,
                task_id=request.task_id,
            ),
        )
        if request.task_id and reply.get("error") is None:
            async_task_service.complete(
                task_id=request.task_id,
                callback_status="SUCCESS",
                result=public_reply(reply),
                trace_id=trace_id,
                message_id=request.message_id,
                parent_message_id=request.parent_message_id,
            )
        return response(reply)
    except BusinessError as exc:
        return response(error_reply(exc, trace_id))


@app.post("/api/v1/projects/{project_id}/members")
def add_project_member(project_id: str, request: AddMemberRequest):
    trace_id = request.trace_id or new_trace_id()
    payload = request.model_dump(exclude={"trace_id", "idempotency_key", "operator_person_id"})
    try:
        return response(governed_call(
            actor_person_id=request.operator_person_id,
            action="project.member.add",
            trace_id=trace_id,
            project_id=project_id,
            payload=payload,
            basis_ref=request.authorization_basis_ref,
            handler=lambda: member_service.add_member(
                project_id=project_id,
                payload=payload,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                operator_person_id=request.operator_person_id,
            ),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, trace_id))


@app.put("/api/v1/projects/{project_id}/members/{person_id}")
def update_project_member(project_id: str, person_id: str, request: UpdateMemberRequest):
    trace_id = request.trace_id or new_trace_id()
    payload = request.model_dump(exclude={"trace_id", "idempotency_key", "operator_person_id"}, exclude_none=True)
    try:
        return response(governed_call(
            actor_person_id=request.operator_person_id,
            action="project.member.update",
            trace_id=trace_id,
            project_id=project_id,
            payload=payload,
            basis_ref=request.change_basis_ref,
            handler=lambda: member_service.update_member(
                project_id=project_id,
                person_id=person_id,
                payload=payload,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                operator_person_id=request.operator_person_id,
            ),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, trace_id))


@app.post("/api/v1/projects/{project_id}/members/{person_id}/remove")
def remove_project_member(project_id: str, person_id: str, request: RemoveMemberRequest):
    trace_id = request.trace_id or new_trace_id()
    payload = request.model_dump(exclude={"trace_id", "idempotency_key", "operator_person_id"})
    try:
        return response(governed_call(
            actor_person_id=request.operator_person_id,
            action="project.member.remove",
            trace_id=trace_id,
            project_id=project_id,
            payload=payload,
            basis_ref=request.revocation_basis_ref,
            handler=lambda: member_service.remove_member(
                project_id=project_id,
                person_id=person_id,
                payload=payload,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                operator_person_id=request.operator_person_id,
            ),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, trace_id))


@app.get("/api/v1/projects/{project_id}/members")
def query_project_members(project_id: str, actor_person_id: str, include_exited: bool = Query(False), trace_id: Optional[str] = Query(None)):
    active_trace_id = trace_id or new_trace_id()
    try:
        return response(governed_call(
            actor_person_id=actor_person_id,
            action="project.member.query",
            trace_id=active_trace_id,
            project_id=project_id,
            payload={"include_exited": include_exited},
            handler=lambda: member_service.query_members(project_id=project_id, trace_id=active_trace_id, include_exited=include_exited),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, active_trace_id))


@app.post("/api/v1/projects/{project_id}/closure")
def close_project(project_id: str, request: ClosureRequest):
    trace_id = request.trace_id or new_trace_id()
    payload = request.model_dump(exclude={"trace_id", "idempotency_key", "operator_person_id", "workflow_instance_id"})
    try:
        return response(governed_call(
            actor_person_id=request.operator_person_id,
            action="project.closure.execute",
            trace_id=trace_id,
            project_id=project_id,
            payload=payload,
            basis_ref=request.closure_basis_ref,
            handler=lambda: closure_service.close_project(
                project_id=project_id,
                payload=payload,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                operator_person_id=request.operator_person_id,
                workflow_instance_id=request.workflow_instance_id,
            ),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, trace_id))


@app.get("/api/v1/projects/{project_id}/archive-catalog")
def query_archive_catalog(project_id: str, actor_person_id: str, trace_id: Optional[str] = Query(None)):
    active_trace_id = trace_id or new_trace_id()
    try:
        return response(governed_call(
            actor_person_id=actor_person_id,
            action="project.archive.catalog.read",
            trace_id=active_trace_id,
            project_id=project_id,
            handler=lambda: archive_service.query_archive_catalog(project_id=project_id, trace_id=active_trace_id),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, active_trace_id))


@app.post("/api/v1/projects/{project_id}/archive-authorizations")
def record_archive_authorization(project_id: str, request: ArchiveAuthorizationRequest):
    trace_id = request.trace_id or new_trace_id()
    payload = request.model_dump(exclude={"trace_id", "idempotency_key", "operator_person_id"})
    try:
        return response(governed_call(
            actor_person_id=request.operator_person_id,
            action="project.archive.authorization.record",
            trace_id=trace_id,
            project_id=project_id,
            payload=payload,
            basis_ref=request.authorization_basis_ref,
            handler=lambda: authorization_service.record_authorization(
                project_id=project_id,
                payload=payload,
                trace_id=trace_id,
                idempotency_key=request.idempotency_key,
                operator_person_id=request.operator_person_id,
            ),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, trace_id))


@app.get("/api/v1/projects/{project_id}/archive-authorizations")
def query_archive_authorizations(project_id: str, actor_person_id: str, applicant_person_id: Optional[str] = Query(None), trace_id: Optional[str] = Query(None)):
    active_trace_id = trace_id or new_trace_id()
    try:
        return response(governed_call(
            actor_person_id=actor_person_id,
            action="project.archive.authorization.query",
            trace_id=active_trace_id,
            project_id=project_id,
            payload={"applicant_person_id": applicant_person_id},
            handler=lambda: authorization_service.query_authorization_records(
                project_id=project_id,
                applicant_person_id=applicant_person_id,
                trace_id=active_trace_id,
            ),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, active_trace_id))


@app.get("/api/v1/projects/{project_id}/authorized-archive-query")
def authorized_archive_query(project_id: str, applicant_person_id: str, requested_action: str = "project.archive.catalog.read", resource_type: Optional[str] = Query(None), trace_id: Optional[str] = Query(None)):
    active_trace_id = trace_id or new_trace_id()
    try:
        return response(governed_call(
            actor_person_id=applicant_person_id,
            action=requested_action,
            trace_id=active_trace_id,
            project_id=project_id,
            payload={"resource_type": resource_type},
            handler=lambda: authorization_service.authorized_archive_query(
                project_id=project_id,
                applicant_person_id=applicant_person_id,
                requested_action=requested_action,
                resource_type=resource_type,
                trace_id=active_trace_id,
            ),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, active_trace_id))


@app.get("/api/v1/dashboard/summary")
def dashboard_summary(actor_person_id: str, trace_id: Optional[str] = Query(None)):
    active_trace_id = trace_id or new_trace_id()
    def handler():
        projects = repository.list_projects()
        status_counts = {}
        total_members = 0
        total_archived = 0
        total_authorizations = 0
        for project in projects:
            status = project["business_status"]
            status_counts[status] = status_counts.get(status, 0) + 1
            total_members += len(repository.list_members(project["project_id"], include_exited=False))
            if status == "ARCHIVED":
                total_archived += 1
            total_authorizations += len(repository.list_access_authorizations(project["project_id"]))
        return {
            "reply_type":"success","trace_id":active_trace_id,"message":"Dashboard 汇总查询成功",
            "data":{
                "project_total":len(projects),"active_member_total":total_members,
                "archived_project_total":total_archived,"archive_authorization_total":total_authorizations,
                "status_counts":status_counts,"mock_mode":True,"version":"0.6.0-stage6",
                "async_task_total":len(repository.list_async_tasks()),
                "action_decision_total":len(repository.get_action_decisions()),
            },
            "error":None,"governance":None,"_http_status":200,
        }
    try:
        return response(governed_call(
            actor_person_id=actor_person_id,
            action="project.dashboard.summary.read",
            trace_id=active_trace_id,
            resource_scope={"resource_type":"project_dashboard"},
            handler=handler,
        ))
    except BusinessError as exc:
        return response(error_reply(exc, active_trace_id))


@app.get("/api/v1/projects")
def list_projects(actor_person_id: str, trace_id: Optional[str] = Query(None)):
    active_trace_id = trace_id or new_trace_id()
    try:
        return response(governed_call(
            actor_person_id=actor_person_id,
            action="project.list.query",
            trace_id=active_trace_id,
            resource_scope={"resource_type":"project_registry"},
            handler=lambda: query_service.list_projects(trace_id=active_trace_id),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, active_trace_id))


@app.get("/api/v1/projects/{project_id}")
def get_project(project_id: str, actor_person_id: str, trace_id: Optional[str] = Query(None)):
    active_trace_id = trace_id or new_trace_id()
    try:
        return response(governed_call(
            actor_person_id=actor_person_id,
            action="project.query",
            trace_id=active_trace_id,
            project_id=project_id,
            handler=lambda: query_service.get_project(project_id=project_id, trace_id=active_trace_id),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, active_trace_id))


@app.get("/api/v1/projects/{project_id}/trace")
def get_project_trace(project_id: str, actor_person_id: str, trace_id: Optional[str] = Query(None)):
    active_trace_id = trace_id or new_trace_id()
    try:
        return response(governed_call(
            actor_person_id=actor_person_id,
            action="project.trace.query",
            trace_id=active_trace_id,
            project_id=project_id,
            handler=lambda: trace_service.query_project_trace(project_id=project_id, trace_id=active_trace_id),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, active_trace_id))


@app.get("/api/v1/projects/{project_id}/governance")
def get_project_governance(project_id: str, actor_person_id: str, trace_id: Optional[str] = Query(None)):
    active_trace_id = trace_id or new_trace_id()
    try:
        return response(governed_call(
            actor_person_id=actor_person_id,
            action="project.governance.query",
            trace_id=active_trace_id,
            project_id=project_id,
            handler=lambda: {
                "reply_type":"success","trace_id":active_trace_id,"message":"项目治理与异步任务证据查询成功",
                "data":{
                    "action_decisions":repository.get_action_decisions(project_id=project_id),
                    "async_tasks":repository.list_async_tasks(project_id=project_id),
                    "grade_change_records":repository.get_grade_change_records(project_id),
                },
                "error":None,"governance":None,"_http_status":200,
            },
        ))
    except BusinessError as exc:
        return response(error_reply(exc, active_trace_id))


@app.post("/api/v1/tasks/{task_id}/progress")
def record_task_progress(task_id: str, request: TaskProgressRequest):
    trace_id = request.trace_id or new_trace_id()
    payload = request.model_dump(exclude={"trace_id", "idempotency_key", "operator_person_id"})
    try:
        return response(governed_call(
            actor_person_id=request.operator_person_id,
            action="project.task.progress.record",
            trace_id=trace_id,
            payload=payload,
            resource_scope={"task_id":task_id},
            handler=lambda: async_task_service.progress(
                task_id=task_id,
                progress_percent=request.progress_percent,
                status_message=request.status_message,
                trace_id=trace_id,
                message_id=request.message_id,
                parent_message_id=request.parent_message_id,
            ),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, trace_id))


@app.post("/api/v1/tasks/{task_id}/final-callback")
def record_task_final_callback(task_id: str, request: TaskFinalCallbackRequest):
    trace_id = request.trace_id or new_trace_id()
    payload = request.model_dump(exclude={"trace_id", "idempotency_key", "operator_person_id"})
    try:
        return response(governed_call(
            actor_person_id=request.operator_person_id,
            action="project.task.final.callback",
            trace_id=trace_id,
            payload=payload,
            resource_scope={"task_id":task_id},
            handler=lambda: async_task_service.complete(
                task_id=task_id,
                callback_status=request.callback_status,
                result=request.result,
                trace_id=trace_id,
                message_id=request.message_id,
                parent_message_id=request.parent_message_id,
            ),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, trace_id))


@app.get("/api/v1/tasks/{task_id}")
def query_task(task_id: str, actor_person_id: str, trace_id: Optional[str] = Query(None)):
    active_trace_id = trace_id or new_trace_id()
    try:
        return response(governed_call(
            actor_person_id=actor_person_id,
            action="project.task.query",
            trace_id=active_trace_id,
            resource_scope={"task_id":task_id},
            handler=lambda: async_task_service.query(task_id=task_id, trace_id=active_trace_id),
        ))
    except BusinessError as exc:
        return response(error_reply(exc, active_trace_id))


def dispatch_internal(message: InternalMessage):
    common = {
        "trace_id": message.trace_id,
        "idempotency_key": message.idempotency_key,
        "operator_person_id": message.actor.person_id,
    }
    action = message.action

    if action in {"project.register.simple", "project.register.major"}:
        payload = dict(message.payload)
        payload["project_grade"] = "MAJOR" if action.endswith("major") else "SIMPLE"
        reply = registration_service.register(
            payload=payload,
            workflow_instance_id=message.context.workflow_instance_id,
            **common,
        )
        if reply["reply_type"] == "accepted":
            reply = attach_async_task(
                reply,
                action="project.approval.wait",
                trace_id=message.trace_id,
                idempotency_key=message.idempotency_key,
                request_payload=payload,
                project_id=reply["data"]["project"]["project_id"],
                workflow_instance_id=message.context.workflow_instance_id,
                node_id=message.context.node_id,
                source_message_id=message.message_id,
                task_id=message.context.task_id,
            )
        return reply

    if action == "project.approval.result.record":
        payload = dict(message.payload)
        project_id = str(payload.pop("project_id", ""))
        reply = lifecycle_service.record_approval_result(
            project_id=project_id,
            payload=payload,
            workflow_instance_id=message.context.workflow_instance_id,
            **common,
        )
        if message.context.task_id:
            async_task_service.complete(
                task_id=message.context.task_id,
                callback_status="SUCCESS",
                result=public_reply(reply),
                trace_id=message.trace_id,
                message_id=message.message_id,
                parent_message_id=message.parent_message_id,
            )
        return reply

    if action == "project.grade.change.request":
        payload = dict(message.payload)
        project_id = str(payload.pop("project_id", ""))
        grade_service.validate_request(project_id=project_id, target_grade=payload.get("target_grade"))
        return async_task_service.accept(
            action=action,
            trace_id=message.trace_id,
            idempotency_key=message.idempotency_key,
            request_payload=payload,
            project_id=project_id,
            workflow_instance_id=message.context.workflow_instance_id,
            node_id=message.context.node_id,
            source_message_id=message.message_id,
            task_id=message.context.task_id,
        )

    if action == "project.grade.change.result.record":
        payload = dict(message.payload)
        project_id = str(payload.pop("project_id", ""))
        reply = grade_service.record_result(
            project_id=project_id,
            payload=payload,
            workflow_instance_id=message.context.workflow_instance_id,
            task_id=message.context.task_id,
            **common,
        )
        if message.context.task_id:
            async_task_service.complete(
                task_id=message.context.task_id,
                callback_status="SUCCESS",
                result=public_reply(reply),
                trace_id=message.trace_id,
                message_id=message.message_id,
                parent_message_id=message.parent_message_id,
            )
        return reply

    if action == "project.member.add":
        payload = dict(message.payload); project_id = str(payload.pop("project_id", ""))
        return member_service.add_member(project_id=project_id, payload=payload, **common)
    if action == "project.member.update":
        payload = dict(message.payload); project_id = str(payload.pop("project_id", "")); person_id = str(payload.pop("person_id", ""))
        return member_service.update_member(project_id=project_id, person_id=person_id, payload=payload, **common)
    if action == "project.member.remove":
        payload = dict(message.payload); project_id = str(payload.pop("project_id", "")); person_id = str(payload.pop("person_id", ""))
        return member_service.remove_member(project_id=project_id, person_id=person_id, payload=payload, **common)
    if action == "project.member.query":
        return member_service.query_members(project_id=str(message.payload.get("project_id", "")), trace_id=message.trace_id, include_exited=bool(message.payload.get("include_exited", False)))
    if action == "project.closure.execute":
        payload = dict(message.payload); project_id = str(payload.pop("project_id", ""))
        return closure_service.close_project(project_id=project_id, payload=payload, workflow_instance_id=message.context.workflow_instance_id, **common)
    if action == "project.archive.catalog.query":
        return archive_service.query_archive_catalog(project_id=str(message.payload.get("project_id", "")), trace_id=message.trace_id)
    if action == "project.archive.authorization.record":
        payload = dict(message.payload); project_id = str(payload.pop("project_id", ""))
        return authorization_service.record_authorization(project_id=project_id, payload=payload, **common)
    if action == "project.archive.authorization.query":
        return authorization_service.query_authorization_records(project_id=str(message.payload.get("project_id", "")), applicant_person_id=message.payload.get("applicant_person_id"), trace_id=message.trace_id)
    if action == "project.archive.authorized.query":
        return authorization_service.authorized_archive_query(
            project_id=str(message.payload.get("project_id", "")),
            applicant_person_id=str(message.payload.get("applicant_person_id", "")),
            requested_action=str(message.payload.get("requested_action", "project.archive.catalog.read")),
            resource_type=message.payload.get("resource_type"),
            trace_id=message.trace_id,
        )
    if action == "project.list.query":
        return query_service.list_projects(trace_id=message.trace_id)
    if action == "project.query":
        return query_service.get_project(project_id=str(message.payload.get("project_id", "")), trace_id=message.trace_id)
    if action == "project.trace.query":
        return trace_service.query_project_trace(project_id=str(message.payload.get("project_id", "")), trace_id=message.trace_id)
    if action == "project.task.progress.record":
        return async_task_service.progress(
            task_id=message.context.task_id,
            progress_percent=int(message.payload.get("progress_percent", 0)),
            status_message=str(message.payload.get("status_message", "")),
            trace_id=message.trace_id,
            message_id=message.message_id,
            parent_message_id=message.parent_message_id,
        )
    if action == "project.task.final.callback":
        return async_task_service.complete(
            task_id=message.context.task_id,
            callback_status=str(message.payload.get("callback_status", "SUCCESS")),
            result=message.payload.get("result") or {},
            trace_id=message.trace_id,
            message_id=message.message_id,
            parent_message_id=message.parent_message_id,
        )
    if action == "project.task.query":
        return async_task_service.query(task_id=str(message.payload.get("task_id") or message.context.task_id or ""), trace_id=message.trace_id)
    raise BusinessError("CAPABILITY_HANDLER_MISSING", "当前版本尚未实现：" + action, http_status=501)


@app.post("/api/v1/l2/internal/messages")
def internal_messages(message: InternalMessage):
    try:
        message_contract.validate(message)
        source_admission.validate(message)
        capability_router.validate(action=message.action, capability_id=message.capability_id)
        if not repository.register_message_receipt({
            "message_id":message.message_id,
            "parent_message_id":message.parent_message_id,
            "trace_id":message.trace_id,
            "source_service_code":message.source.service_code,
            "route_type":message.route_type,
            "action":message.action,
        }):
            raise BusinessError("DUPLICATE_MESSAGE_ID", "message_id 已经处理过", http_status=409)
        project_id = message.payload.get("project_id")
        reply = governed_call(
            actor_person_id=message.actor.person_id,
            action=message.action,
            trace_id=message.trace_id,
            project_id=str(project_id) if project_id else None,
            payload=message.payload,
            resource_scope={"project_id":project_id,"task_id":message.context.task_id},
            handler=lambda: dispatch_internal(message),
        )
        return response(reply)
    except BusinessError as exc:
        return response(error_reply(exc, message.trace_id))


if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run(
        "api_server:app",
        host=os.environ.get("PROJECT_ENGINE_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("PROJECT_ENGINE_API_PORT", "8008")),
        reload=False,
    )
