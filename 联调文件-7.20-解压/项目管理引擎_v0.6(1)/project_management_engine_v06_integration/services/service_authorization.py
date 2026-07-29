from __future__ import annotations

from datetime import datetime, timezone

from core.errors import BusinessError
from core.idempotency import get_cached_reply, save_reply
from core.standard_reply import failed, success


def utc_now():
    return datetime.now(timezone.utc)


def utc_now_text():
    return utc_now().isoformat()


def parse_iso_datetime(value, field_name):
    if not value:
        raise BusinessError(
            "AUTHORIZATION_TIME_REQUIRED",
            field_name + " 不能为空",
            http_status=400,
        )

    normalized = str(value).strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise BusinessError(
            "INVALID_AUTHORIZATION_TIME",
            field_name + " 不是有效的 ISO 8601 时间",
            http_status=400,
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


class ProjectArchiveAuthorizationService:
    def __init__(
        self,
        repository,
        account_gateway,
        permission_management
    ):
        self.repository = repository
        self.account_gateway = account_gateway
        self.permission_management = permission_management

    def _require_archived_project(self, project_id):
        project = self.repository.get_project(project_id)
        if project is None:
            raise BusinessError(
                "PROJECT_NOT_FOUND",
                "项目不存在：" + project_id,
                http_status=404,
            )

        if project["business_status"] != "ARCHIVED":
            raise BusinessError(
                "PROJECT_NOT_ARCHIVED",
                "只有已封存项目可以办理封存后重新授权与事后查询",
                http_status=409,
            )
        return project

    def record_authorization(
        self,
        *,
        project_id,
        payload,
        trace_id,
        idempotency_key,
        operator_person_id
    ):
        action = "project.archive.authorization.record"
        request_payload = {"project_id": project_id}
        request_payload.update(payload)

        cached = get_cached_reply(
            self.repository,
            idempotency_key=idempotency_key,
            action=action,
            payload=request_payload,
        )
        if cached is not None:
            return cached

        self._require_archived_project(project_id)

        applicant_person_id = str(
            payload.get("applicant_person_id", "")
        ).strip()
        allowed_actions = payload.get("allowed_actions") or []
        allowed_scope = payload.get("allowed_scope") or {
            "project_id": project_id,
            "catalog_only": True,
        }
        basis_ref = payload.get("authorization_basis_ref")
        valid_from_value = (
            payload.get("valid_from") or utc_now_text()
        )
        valid_until_value = payload.get("valid_until")

        if not applicant_person_id:
            raise BusinessError(
                "APPLICANT_PERSON_REQUIRED",
                "查阅申请人编号不能为空",
                http_status=400,
            )

        if not allowed_actions:
            raise BusinessError(
                "ALLOWED_ACTIONS_REQUIRED",
                "重新授权必须明确允许动作",
                http_status=400,
            )

        if not basis_ref:
            raise BusinessError(
                "ARCHIVE_AUTHORIZATION_BASIS_REQUIRED",
                "重新授权必须提供授权文件或制度依据引用",
                http_status=400,
            )

        valid_from = parse_iso_datetime(
            valid_from_value,
            "valid_from",
        )
        valid_until = parse_iso_datetime(
            valid_until_value,
            "valid_until",
        )

        if valid_until <= valid_from:
            raise BusinessError(
                "INVALID_AUTHORIZATION_PERIOD",
                "valid_until 必须晚于 valid_from",
                http_status=400,
            )

        if allowed_scope.get("project_id") not in {
            None,
            project_id,
        }:
            raise BusinessError(
                "AUTHORIZATION_SCOPE_PROJECT_MISMATCH",
                "授权范围中的项目编号与当前项目不一致",
                http_status=400,
            )

        allowed_scope = dict(allowed_scope)
        allowed_scope["project_id"] = project_id
        allowed_scope.setdefault("catalog_only", True)

        person = self.account_gateway.resolve_person(
            applicant_person_id
        )
        if not person["active"]:
            raise BusinessError(
                "PERSON_INACTIVE",
                "查阅申请人账号当前不是有效状态",
                http_status=409,
            )

        decision = self.permission_management.decide(
            person_id=applicant_person_id,
            action="project.archive.access.authorize",
            resource_scope=allowed_scope,
            allowed_actions=allowed_actions,
            valid_from=valid_from.isoformat(),
            valid_until=valid_until.isoformat(),
            basis_ref=basis_ref,
        )

        record = {
            "authorization_record_id": (
                self.repository.new_access_authorization_id()
            ),
            "project_id": project_id,
            "applicant_person_id": applicant_person_id,
            "applicant_name": person["display_name"],
            "allowed_actions": allowed_actions,
            "allowed_scope": allowed_scope,
            "authorization_basis_ref": basis_ref,
            "decision_id": decision["decision_id"],
            "decision_result": (
                "ALLOW" if decision["allow"] else "DENY"
            ),
            "decision_reason": decision["reason"],
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
            "operator_person_id": operator_person_id,
            "trace_id": trace_id,
            "created_at": utc_now_text(),
        }
        self.repository.append_access_authorization(record)

        if not decision["allow"]:
            reply = failed(
                trace_id=trace_id,
                code="ARCHIVE_AUTHORIZATION_DENIED",
                message="权限管理拒绝封存项目重新授权",
                http_status=403,
            )
            save_reply(
                self.repository,
                idempotency_key=idempotency_key,
                action=action,
                payload=request_payload,
                reply=reply,
            )
            return reply

        reply = success(
            trace_id=trace_id,
            data={
                "authorization": (
                    self.repository.list_access_authorizations(
                        project_id,
                        applicant_person_id,
                    )[0]
                ),
                "permission_decision": decision,
            },
            message="封存项目重新授权登记成功",
            http_status=201,
        )
        save_reply(
            self.repository,
            idempotency_key=idempotency_key,
            action=action,
            payload=request_payload,
            reply=reply,
        )
        return reply

    def authorized_archive_query(
        self,
        *,
        project_id,
        applicant_person_id,
        requested_action,
        trace_id,
        resource_type=None
    ):
        project = self._require_archived_project(project_id)

        person = self.account_gateway.resolve_person(
            applicant_person_id
        )
        if not person["active"]:
            raise BusinessError(
                "PERSON_INACTIVE",
                "查阅申请人账号当前不是有效状态",
                http_status=409,
            )

        records = self.repository.list_access_authorizations(
            project_id,
            applicant_person_id,
        )
        if not records:
            raise BusinessError(
                "ARCHIVE_AUTHORIZATION_REQUIRED",
                "查询封存项目之前必须先完成重新授权",
                http_status=403,
            )

        matching_records = [
            record
            for record in records
            if requested_action in record["allowed_actions"]
        ]
        if not matching_records:
            raise BusinessError(
                "ARCHIVE_ACTION_NOT_ALLOWED",
                "现有授权不包含本次查询动作",
                http_status=403,
            )

        authorization = matching_records[0]

        if authorization["decision_result"] != "ALLOW":
            raise BusinessError(
                "ARCHIVE_AUTHORIZATION_DENIED",
                "最近一次匹配授权结论不是允许",
                http_status=403,
            )

        now = utc_now()
        valid_from = parse_iso_datetime(
            authorization["valid_from"],
            "valid_from",
        )
        valid_until = parse_iso_datetime(
            authorization["valid_until"],
            "valid_until",
        )

        if now < valid_from:
            raise BusinessError(
                "ARCHIVE_AUTHORIZATION_NOT_EFFECTIVE",
                "封存项目授权尚未生效",
                http_status=403,
            )

        if now >= valid_until:
            raise BusinessError(
                "ARCHIVE_AUTHORIZATION_EXPIRED",
                "封存项目授权已经过期",
                http_status=403,
            )

        allowed_scope = authorization["allowed_scope"]
        allowed_resource_types = allowed_scope.get(
            "resource_types"
        )
        if (
            resource_type
            and allowed_resource_types
            and resource_type not in allowed_resource_types
        ):
            raise BusinessError(
                "ARCHIVE_SCOPE_NOT_ALLOWED",
                "现有授权范围不包含请求的资源类型",
                http_status=403,
            )

        archive_catalog = self.repository.get_archive_catalog(
            project_id
        )
        if resource_type:
            archive_catalog = [
                item
                for item in archive_catalog
                if item["resource_type"] == resource_type
            ]

        # 只返回目录元数据和引用，不在项目管理引擎内返回原始正文。
        safe_catalog = []
        for item in archive_catalog:
            safe_catalog.append({
                "catalog_item_id": item["catalog_item_id"],
                "resource_type": item["resource_type"],
                "resource_name": item["resource_name"],
                "data_ref": item.get("data_ref"),
                "artifact_ref": item.get("artifact_ref"),
                "asset_ref": item.get("asset_ref"),
                "version": item.get("version"),
                "data_labels": item.get("data_labels", []),
                "archive_status": item["archive_status"],
                "sealed_at": item.get("sealed_at"),
            })

        return success(
            trace_id=trace_id,
            data={
                "project": {
                    "project_id": project["project_id"],
                    "project_name": project["project_name"],
                    "project_category": project["project_category"],
                    "business_status": project["business_status"],
                    "archived_at": project["archived_at"],
                },
                "applicant": {
                    "person_id": applicant_person_id,
                    "display_name": person["display_name"],
                },
                "requested_action": requested_action,
                "authorization": authorization,
                "archive_catalog": safe_catalog,
                "content_included": False,
                "content_access_note": (
                    "项目管理引擎仅返回目录及引用；"
                    "原始内容应由数据操作或文件服务按引用继续办理。"
                ),
            },
            message="封存项目授权查询成功",
        )

    def query_authorization_records(
        self,
        *,
        project_id,
        trace_id,
        applicant_person_id=None
    ):
        project = self.repository.get_project(project_id)
        if project is None:
            raise BusinessError(
                "PROJECT_NOT_FOUND",
                "项目不存在：" + project_id,
                http_status=404,
            )

        return success(
            trace_id=trace_id,
            data={
                "project_id": project_id,
                "authorization_records": (
                    self.repository.list_access_authorizations(
                        project_id,
                        applicant_person_id,
                    )
                ),
            },
            message="封存项目授权记录查询成功",
        )
