from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from uuid import uuid4

BASE_URL = os.environ.get(
    "PROJECT_ENGINE_BASE_URL",
    "http://127.0.0.1:8008",
).rstrip("/")


def request(method, path, payload=None, expected=None):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8", errors="replace")

    result = json.loads(body) if body else {}
    if expected is not None and status != expected:
        raise AssertionError(
            f"{method} {path}: HTTP {status}, expected {expected}, {result}"
        )
    return status, result


def main():
    suffix = uuid4().hex[:8].upper()

    print("[1/6] 健康检查")
    _, health = request("GET", "/health", expected=200)
    assert health["version"] == "0.6.0-stage6"

    print("[2/6] 普通项目登记")
    register_payload = {
        "project_name": "联调测试项目-" + suffix,
        "project_category": "数字化建设",
        "project_grade": "SIMPLE",
        "budget_attribute": "一般预算",
        "initiator_person_id": "PERSON_INTEGRATION_001",
        "description": "最小联调客户端创建",
        "idempotency_key": "IDEMP_REGISTER_" + suffix,
    }
    _, registered = request(
        "POST",
        "/api/v1/projects/register",
        register_payload,
        expected=201,
    )
    project_id = registered["data"]["project"]["project_id"]
    assert registered["data"]["project"]["business_status"] == "ACTIVE"

    print("[3/6] 成员加入")
    member_payload = {
        "person_id": "PERSON_101",
        "position_code": "POSITION_PROJECT_MEMBER",
        "project_role": "项目成员",
        "permission_scope": {"project_id": project_id},
        "allowed_actions": ["project.read"],
        "authorization_basis_ref": "BASIS_INTEGRATION_ADD",
        "operator_person_id": "PERSON_INTEGRATION_MANAGER",
        "idempotency_key": "IDEMP_MEMBER_" + suffix,
    }
    request(
        "POST",
        f"/api/v1/projects/{project_id}/members",
        member_payload,
        expected=201,
    )

    print("[4/6] 统一消息入口查询")
    message = {
        "protocol_version": "1.0",
        "message_id": "MSG_QUERY_" + suffix,
        "trace_id": "TRACE_QUERY_" + suffix,
        "request_id": "REQ_QUERY_" + suffix,
        "source": {
            "layer": "L2",
            "service_code": "l2.interface_control",
        },
        "target": {
            "layer": "L2",
            "service_code": "l2.project_management",
        },
        "channel": "l2_internal",
        "route_type": "query.request",
        "action": "project.query",
        "capability_id": "CAP.PROJECT.QUERY",
        "capability_dictionary_version": "2026.07.v06",
        "registry_version": "registry_2026.07.v06",
        "actor": {
            "person_id": "PERSON_INTEGRATION_001",
            "tenant_id": "tenant_hanhe",
        },
        "context": {},
        "idempotency_key": "IDEMP_QUERY_" + suffix,
        "payload": {"project_id": project_id},
    }
    _, queried = request(
        "POST",
        "/api/v1/l2/internal/messages",
        message,
        expected=200,
    )
    assert queried["data"]["project"]["project_id"] == project_id

    print("[5/6] 重复 message_id 拦截（预期 409）")
    _, duplicate = request(
        "POST",
        "/api/v1/l2/internal/messages",
        message,
        expected=409,
    )
    assert duplicate["error"]["code"] == "DUPLICATE_MESSAGE_ID"

    print("[6/6] 全过程追踪")
    _, trace = request(
        "GET",
        f"/api/v1/projects/{project_id}/trace"
        "?actor_person_id=PERSON_INTEGRATION_001",
        expected=200,
    )
    assert trace["data"]["project_id"] == project_id
    assert len(trace["data"]["members"]) >= 1

    result = {
        "result": "PASS",
        "project_id": project_id,
        "validated_items": [
            "健康检查",
            "普通项目登记",
            "成员加入",
            "统一消息入口查询",
            "重复消息拦截",
            "全过程追踪",
        ],
        "boundary": (
            "仅表示本地 Mock 联调验证通过，"
            "不代表真实平台联合验收。"
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("联调测试失败：", exc)
        sys.exit(1)
