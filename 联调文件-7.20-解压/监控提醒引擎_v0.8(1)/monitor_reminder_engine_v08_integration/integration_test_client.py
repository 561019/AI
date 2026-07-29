from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


URL = "http://127.0.0.1:8020/api/v1/l2/internal/messages"
HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json",
    "X-Source-Module": "workflow_engine_demo",
    "X-Operator-ID": "WORKFLOW_SYSTEM",
    "X-Permission-Token": "WF_DEMO_TOKEN_V07",
}


def call(envelope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = Request(
        URL,
        data=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
        headers={**HEADERS, "X-Request-ID": envelope["request_id"]},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError("无法连接 API，请先运行 python api_server.py") from exc


def envelope(
    *, suffix: str, action: str, capability_id: str,
    payload: dict[str, Any], idempotency_key: str,
    source_service: str = "l2.workflow_execution",
) -> dict[str, Any]:
    return {
        "protocol_version": "1.0",
        "message_id": f"msg_{action.replace('.', '_')}_{suffix}",
        "trace_id": f"TRACE_LAYER_V08_{suffix}",
        "request_id": f"REQ_{action.replace('.', '_').upper()}_{suffix}",
        "parent_message_id": f"msg_parent_{suffix}",
        "source": {"layer": "L2", "service_code": source_service},
        "target": {"layer": "L2", "service_code": "l2.monitor_reminder"},
        "channel": "l2_internal",
        "route_type": "task.dispatch",
        "action": action,
        "capability_id": capability_id,
        "capability_dictionary_version": "local-draft-2026.07.17",
        "registry_version": "local-registry-2026.07.17",
        "actor": {"person_id": "WORKFLOW_SYSTEM", "tenant_id": "tenant_hanhe"},
        "context": {
            "workflow_instance_id": f"FLOW_{suffix}",
            "node_id": f"NODE_{action.replace('.', '_').upper()}",
            "task_id": f"TASK_{action.replace('.', '_').upper()}_{suffix}",
            "data_refs": [],
        },
        "idempotency_key": idempotency_key,
        "deadline_at": (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat(timespec="seconds"),
        "payload": payload,
    }


def check(title: str, actual: int, expected: int, body: dict[str, Any]) -> None:
    print(f"{title}: HTTP {actual}, reply_type={body.get('reply_type')}")
    if actual != expected:
        raise RuntimeError(json.dumps(body, ensure_ascii=False, indent=2))


def main() -> None:
    suffix = datetime.now().strftime("%Y%m%d%H%M%S")
    item_id = f"ITEM_LAYER_V08_{suffix}"
    trace_id = f"TRACE_LAYER_V08_{suffix}"

    print("=" * 76)
    print("监控提醒引擎 v0.8 第一阶段：统一层内接口测试")
    print("=" * 76)

    invalid = envelope(
        suffix=suffix,
        action="monitor.item.register",
        capability_id="CAP.MONITOR.ITEM.REGISTER",
        idempotency_key=f"IDEM_INVALID_{suffix}",
        source_service="l2.rule_calculation",
        payload={
            "item_id": f"INVALID_{item_id}",
            "object_type": "metric",
            "object_id": "INVALID",
            "rule_id": "RULE_INVALID",
            "receiver_role": "总经办岗位",
        },
    )
    status, body = call(invalid)
    check("错误来源准入拒绝", status, 400, body)

    register = envelope(
        suffix=suffix,
        action="monitor.item.register",
        capability_id="CAP.MONITOR.ITEM.REGISTER",
        idempotency_key=f"IDEM_REGISTER_{suffix}",
        payload={
            "item_id": item_id,
            "object_type": "business_metric",
            "object_id": "SALES_GROWTH_RATE",
            "rule_id": "RULE_SALES_DROP_10_PERCENT",
            "trigger_time": "按周期检查",
            "rule_version": "v1.0",
            "receiver_role": "总经办岗位",
            "delivery_channel": "platform_notice",
            "notice_type": "经营指标预警",
            "alert_level": "warning",
            "dedup_key": f"SALES_DROP_{suffix}",
            "repeat_interval": 600,
        },
    )
    status, body = call(register)
    check("统一信封登记", status, 201, body)

    status, replay = call(register)
    check("相同幂等请求重放", status, 201, replay)
    if not replay.get("meta", {}).get("idempotency_replayed"):
        raise RuntimeError("幂等重放标记缺失")

    conflict = json.loads(json.dumps(register, ensure_ascii=False))
    conflict["payload"]["object_id"] = "CHANGED_VALUE"
    status, body = call(conflict)
    check("同幂等键不同内容冲突", status, 409, body)

    reminder = envelope(
        suffix=suffix,
        action="reminder.handle",
        capability_id="CAP.MONITOR.REMINDER.HANDLE",
        idempotency_key=f"IDEM_REMINDER_{suffix}",
        payload={
            "item_id": item_id,
            "judgement_result": {
                "triggered": True,
                "rule_id": "RULE_SALES_DROP_10_PERCENT",
                "rule_version": "v1.0",
                "reason": "规则计算引擎已判定销售增长率触发预警",
                "scene_type": "metric_warning",
                "metric_name": "销售增长率",
                "actual_value": "-12%",
                "boundary": "低于 -10% 预警线",
                "data_source": "经营日报表",
            },
        },
    )
    status, body = call(reminder)
    check("提醒办理返回受理回执", status, 202, body)

    query = envelope(
        suffix=suffix,
        action="monitor.trace.query",
        capability_id="CAP.MONITOR.TRACE.QUERY",
        idempotency_key=f"IDEM_TRACE_{suffix}",
        payload={"trace_id": trace_id},
    )
    status, body = call(query)
    check("全过程追踪查询", status, 200, body)
    total = body.get("data", {}).get("total_records", 0)
    if total <= 0:
        raise RuntimeError("全过程追踪记录为空")

    print("\n统一消息信封：通过")
    print("流程执行引擎来源准入：通过")
    print("能力编号与 action 匹配：通过")
    print("success / accepted / failed：通过")
    print("幂等重放与冲突检测：通过")
    print(f"全过程追踪编号：{trace_id}")
    print("监控提醒引擎 v0.8 第一阶段测试完成。")


if __name__ == "__main__":
    main()
