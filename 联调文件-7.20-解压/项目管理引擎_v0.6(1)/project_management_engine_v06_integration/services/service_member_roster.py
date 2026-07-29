from __future__ import annotations

from datetime import datetime, timezone

from core.errors import BusinessError
from core.idempotency import get_cached_reply, save_reply
from core.standard_reply import failed, success


def utc_now_text():
    return datetime.now(timezone.utc).isoformat()


class ProjectMemberRosterService:
    def __init__(
        self,
        repository,
        account_gateway,
        permission_management
    ):
        self.repository = repository
        self.account_gateway = account_gateway
        self.permission_management = permission_management

    def _require_active_project(self, project_id):
        project = self.repository.get_project(project_id)
        if project is None:
            raise BusinessError(
                "PROJECT_NOT_FOUND",
                "项目不存在：" + project_id,
                http_status=404,
            )
        if project["business_status"] != "ACTIVE":
            raise BusinessError(
                "PROJECT_STATE_NOT_ALLOWED",
                "只有进行中的项目可以维护成员名册",
                http_status=409,
            )
        return project

    def add_member(
        self,
        *,
        project_id,
        payload,
        trace_id,
        idempotency_key,
        operator_person_id
    ):
        action = "project.member.add"
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

        self._require_active_project(project_id)

        person_id = str(payload.get("person_id", "")).strip()
        project_role = str(payload.get("project_role", "")).strip()
        position_code = str(payload.get("position_code", "")).strip()
        permission_scope = payload.get("permission_scope") or {
            "project_id": project_id
        }
        allowed_actions = payload.get("allowed_actions") or ["project.read"]
        valid_from = payload.get("valid_from")
        valid_until = payload.get("valid_until")
        basis_ref = payload.get("authorization_basis_ref")

        if not project_role:
            raise BusinessError(
                "PROJECT_ROLE_REQUIRED",
                "项目角色不能为空",
                http_status=400,
            )
        if not position_code:
            raise BusinessError(
                "POSITION_CODE_REQUIRED",
                "岗位编号不能为空",
                http_status=400,
            )
        if not basis_ref:
            raise BusinessError(
                "AUTHORIZATION_BASIS_REQUIRED",
                "成员加入项目必须提供授权依据引用",
                http_status=400,
            )

        existing = self.repository.get_active_member(project_id, person_id)
        if existing is not None:
            raise BusinessError(
                "MEMBER_ALREADY_ACTIVE",
                "该人员已经是项目有效成员",
                http_status=409,
            )

        person = self.account_gateway.resolve_person(
            person_id,
            requested_position_code=position_code,
        )
        if not person["active"]:
            raise BusinessError(
                "PERSON_INACTIVE",
                "该人员账号当前不是有效状态",
                http_status=409,
            )

        decision = self.permission_management.decide(
            person_id=person_id,
            action="project.member.authorize",
            resource_scope=permission_scope,
            allowed_actions=allowed_actions,
            valid_from=valid_from,
            valid_until=valid_until,
            basis_ref=basis_ref,
        )

        self.repository.append_permission_record(
            member_record_id=None,
            project_id=project_id,
            person_id=person_id,
            permission_action="AUTHORIZE",
            requested_scope=permission_scope,
            allowed_actions=allowed_actions,
            valid_from=valid_from,
            valid_until=valid_until,
            basis_ref=basis_ref,
            decision_id=decision["decision_id"],
            decision_result="ALLOW" if decision["allow"] else "DENY",
            decision_reason=decision["reason"],
            operator_person_id=operator_person_id,
            trace_id=trace_id,
        )

        if not decision["allow"]:
            self.repository.append_member_event(
                member_record_id=None,
                project_id=project_id,
                person_id=person_id,
                event_type="MEMBER_AUTHORIZATION_DENIED",
                event_result="FAILED",
                project_role=project_role,
                position_code=position_code,
                decision_id=decision["decision_id"],
                reason=decision["reason"],
                operator_person_id=operator_person_id,
                trace_id=trace_id,
            )
            reply = failed(
                trace_id=trace_id,
                code="MEMBER_AUTHORIZATION_DENIED",
                message="权限管理拒绝成员加入项目授权",
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

        member_record_id = self.repository.new_member_record_id()
        joined_at = utc_now_text()
        member = {
            "member_record_id": member_record_id,
            "project_id": project_id,
            "person_id": person_id,
            "person_name": person["display_name"],
            "position_code": person["position_code"],
            "project_role": project_role,
            "permission_scope": permission_scope,
            "allowed_actions": allowed_actions,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "authorization_basis_ref": basis_ref,
            "joined_at": joined_at,
            "last_decision_id": decision["decision_id"],
            "last_trace_id": trace_id,
        }
        self.repository.create_active_member(member)
        self.repository.append_member_event(
            member_record_id=member_record_id,
            project_id=project_id,
            person_id=person_id,
            event_type="MEMBER_JOINED",
            event_result="SUCCESS",
            project_role=project_role,
            position_code=position_code,
            decision_id=decision["decision_id"],
            reason="成员授权成功并登记进入名册",
            operator_person_id=operator_person_id,
            trace_id=trace_id,
        )

        reply = success(
            trace_id=trace_id,
            data={
                "member": self.repository.get_active_member(
                    project_id,
                    person_id,
                ),
                "permission_decision": decision,
            },
            message="成员加入项目并完成授权登记",
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

    def remove_member(
        self,
        *,
        project_id,
        person_id,
        payload,
        trace_id,
        idempotency_key,
        operator_person_id
    ):
        action = "project.member.remove"
        request_payload = {
            "project_id": project_id,
            "person_id": person_id,
        }
        request_payload.update(payload)

        cached = get_cached_reply(
            self.repository,
            idempotency_key=idempotency_key,
            action=action,
            payload=request_payload,
        )
        if cached is not None:
            return cached

        self._require_active_project(project_id)

        member = self.repository.get_active_member(project_id, person_id)
        if member is None:
            raise BusinessError(
                "MEMBER_NOT_ACTIVE",
                "该人员不是项目当前有效成员",
                http_status=404,
            )

        basis_ref = payload.get("revocation_basis_ref")
        if not basis_ref:
            raise BusinessError(
                "REVOCATION_BASIS_REQUIRED",
                "成员退出项目必须提供收权依据引用",
                http_status=400,
            )

        permission_scope = member["permission_scope"]
        allowed_actions = member["allowed_actions"]

        decision = self.permission_management.decide(
            person_id=person_id,
            action="project.member.revoke",
            resource_scope=permission_scope,
            allowed_actions=allowed_actions,
            basis_ref=basis_ref,
        )

        self.repository.append_permission_record(
            member_record_id=member["member_record_id"],
            project_id=project_id,
            person_id=person_id,
            permission_action="REVOKE",
            requested_scope=permission_scope,
            allowed_actions=allowed_actions,
            basis_ref=basis_ref,
            decision_id=decision["decision_id"],
            decision_result="ALLOW" if decision["allow"] else "DENY",
            decision_reason=decision["reason"],
            operator_person_id=operator_person_id,
            trace_id=trace_id,
        )

        if not decision["allow"]:
            self.repository.append_member_event(
                member_record_id=member["member_record_id"],
                project_id=project_id,
                person_id=person_id,
                event_type="MEMBER_REVOCATION_DENIED",
                event_result="FAILED",
                project_role=member["project_role"],
                position_code=member["position_code"],
                decision_id=decision["decision_id"],
                reason=decision["reason"],
                operator_person_id=operator_person_id,
                trace_id=trace_id,
            )
            reply = failed(
                trace_id=trace_id,
                code="MEMBER_REVOCATION_DENIED",
                message="权限管理未完成收权，成员仍保留有效状态",
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

        left_at = utc_now_text()
        self.repository.exit_member(
            member_record_id=member["member_record_id"],
            left_at=left_at,
            decision_id=decision["decision_id"],
            trace_id=trace_id,
        )
        self.repository.append_member_event(
            member_record_id=member["member_record_id"],
            project_id=project_id,
            person_id=person_id,
            event_type="MEMBER_EXITED",
            event_result="SUCCESS",
            project_role=member["project_role"],
            position_code=member["position_code"],
            decision_id=decision["decision_id"],
            reason=payload.get("exit_reason") or "成员退出并完成收权",
            operator_person_id=operator_person_id,
            trace_id=trace_id,
        )

        reply = success(
            trace_id=trace_id,
            data={
                "member": self.repository.get_latest_member(
                    project_id,
                    person_id,
                ),
                "permission_decision": decision,
            },
            message="成员退出项目并完成收权登记",
        )
        save_reply(
            self.repository,
            idempotency_key=idempotency_key,
            action=action,
            payload=request_payload,
            reply=reply,
        )
        return reply

    def update_member(
        self,
        *,
        project_id,
        person_id,
        payload,
        trace_id,
        idempotency_key,
        operator_person_id
    ):
        action = "project.member.update"
        request_payload = {"project_id": project_id, "person_id": person_id}
        request_payload.update(payload)
        cached = get_cached_reply(
            self.repository,
            idempotency_key=idempotency_key,
            action=action,
            payload=request_payload,
        )
        if cached is not None:
            return cached
        self._require_active_project(project_id)
        current = self.repository.get_active_member(project_id, person_id)
        if current is None:
            raise BusinessError("MEMBER_NOT_ACTIVE", "该人员不是项目当前有效成员", http_status=404)
        basis_ref = payload.get("change_basis_ref")
        if not basis_ref:
            raise BusinessError("MEMBER_CHANGE_BASIS_REQUIRED", "成员变更必须提供变更依据引用", http_status=400)
        desired = {
            "position_code": str(payload.get("position_code") or current["position_code"]).strip(),
            "project_role": str(payload.get("project_role") or current["project_role"]).strip(),
            "permission_scope": payload.get("permission_scope") or current["permission_scope"],
            "allowed_actions": payload.get("allowed_actions") or current["allowed_actions"],
            "valid_from": payload.get("valid_from", current.get("valid_from")),
            "valid_until": payload.get("valid_until", current.get("valid_until")),
        }
        changed = any([
            desired["position_code"] != current["position_code"],
            desired["project_role"] != current["project_role"],
            desired["permission_scope"] != current["permission_scope"],
            desired["allowed_actions"] != current["allowed_actions"],
            desired["valid_from"] != current.get("valid_from"),
            desired["valid_until"] != current.get("valid_until"),
        ])
        if not changed:
            raise BusinessError("MEMBER_CHANGE_EMPTY", "成员变更内容与当前记录一致", http_status=409)
        person = self.account_gateway.resolve_person(person_id, requested_position_code=desired["position_code"])
        if not person["active"]:
            raise BusinessError("PERSON_INACTIVE", "该人员账号当前不是有效状态", http_status=409)
        decision = self.permission_management.decide(
            person_id=person_id,
            action="project.member.update",
            resource_scope=desired["permission_scope"],
            allowed_actions=desired["allowed_actions"],
            valid_from=desired["valid_from"],
            valid_until=desired["valid_until"],
            basis_ref=basis_ref,
        )
        self.repository.append_permission_record(
            member_record_id=current["member_record_id"], project_id=project_id,
            person_id=person_id, permission_action="UPDATE",
            requested_scope=desired["permission_scope"], allowed_actions=desired["allowed_actions"],
            valid_from=desired["valid_from"], valid_until=desired["valid_until"], basis_ref=basis_ref,
            decision_id=decision["decision_id"], decision_result="ALLOW" if decision["allow"] else "DENY",
            decision_reason=decision["reason"], operator_person_id=operator_person_id, trace_id=trace_id,
        )
        if not decision["allow"]:
            self.repository.append_member_event(
                member_record_id=current["member_record_id"], project_id=project_id, person_id=person_id,
                event_type="MEMBER_UPDATE_DENIED", event_result="FAILED", project_role=current["project_role"],
                position_code=current["position_code"], decision_id=decision["decision_id"], reason=decision["reason"],
                operator_person_id=operator_person_id, trace_id=trace_id,
            )
            reply = failed(trace_id=trace_id, code="MEMBER_UPDATE_DENIED", message="权限管理拒绝成员信息或权限范围变更", http_status=403)
            save_reply(self.repository,idempotency_key=idempotency_key,action=action,payload=request_payload,reply=reply)
            return reply
        changed_at = utc_now_text()
        self.repository.supersede_member(member_record_id=current["member_record_id"], ended_at=changed_at, decision_id=decision["decision_id"], trace_id=trace_id)
        new_id = self.repository.new_member_record_id()
        self.repository.create_active_member({
            "member_record_id":new_id,"project_id":project_id,"person_id":person_id,"person_name":person["display_name"],
            "position_code":desired["position_code"],"project_role":desired["project_role"],
            "permission_scope":desired["permission_scope"],"allowed_actions":desired["allowed_actions"],
            "valid_from":desired["valid_from"],"valid_until":desired["valid_until"],"authorization_basis_ref":basis_ref,
            "joined_at":changed_at,"last_decision_id":decision["decision_id"],"last_trace_id":trace_id,
        })
        self.repository.append_member_event(
            member_record_id=new_id, project_id=project_id, person_id=person_id,
            event_type="MEMBER_UPDATED", event_result="SUCCESS", project_role=desired["project_role"],
            position_code=desired["position_code"], decision_id=decision["decision_id"],
            reason=payload.get("change_reason") or "成员角色、岗位或权限范围变更",
            operator_person_id=operator_person_id, trace_id=trace_id,
        )
        reply = success(
            trace_id=trace_id,
            data={"member":self.repository.get_active_member(project_id,person_id),"previous_member_record_id":current["member_record_id"],"permission_decision":decision},
            message="成员信息与权限范围变更已登记",
        )
        save_reply(self.repository,idempotency_key=idempotency_key,action=action,payload=request_payload,reply=reply)
        return reply

    def query_members(
        self,
        *,
        project_id,
        trace_id,
        include_exited=False
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
                "include_exited": include_exited,
                "members": self.repository.list_members(
                    project_id,
                    include_exited=include_exited,
                ),
                "member_events": self.repository.get_member_events(
                    project_id
                ),
                "permission_records": self.repository.get_permission_records(
                    project_id
                ),
            },
            message="项目成员名册查询成功",
        )
