import os
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    os.environ["HUMAN_COLLAB_DB"] = os.path.join(tmp, "smoke.db")

    from fastapi.testclient import TestClient
    import main

    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200

        envelope = main.demo_envelope(
            title="冒烟测试任务",
            collaboration_type="approval_review",
            work_mode="on_loop",
            trigger_source_module="l2.rule_calculation",
            content="需要人工确认",
            ai_result="上游结果",
            evidence_summary="测试依据",
            risk_level="high",
            target_person_id="approver_001",
            scene_code="SMOKE",
        )
        create_response = client.post(
            "/api/v1/human-tasks", json=main.model_to_dict(envelope)
        )
        assert create_response.status_code == 202, create_response.text
        task_id = create_response.json()["data"]["human_task_id"]

        task = client.get(f"/api/v1/human-tasks/{task_id}").json()["data"]
        decision = {
            "protocol_version": "1.0",
            "message_id": "msg_smoke_decision",
            "trace_id": task["trace_id"],
            "request_id": "req_smoke_decision",
            "parent_message_id": task["message_id"],
            "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
            "target": {"layer": "L1", "service_code": "l1.human_collaboration"},
            "channel": "l2_to_l1",
            "route_type": "command.handoff",
            "action": "human.task.respond",
            "actor": {"person_id": "approver_001", "tenant_id": "tenant_demo"},
            "context": {
                "workflow_instance_id": task["workflow_instance_id"],
                "node_id": task["node_id"],
                "task_id": task["upstream_task_id"],
                "data_refs": [],
                "artifact_refs": [],
            },
            "idempotency_key": "smoke-decision-v1",
            "payload": {
                "decision": "modify_approve",
                "modified_result": "人工修正后的确定结果",
                "comment": "已复核。",
            },
        }
        decision_response = client.post(
            f"/api/v1/human-tasks/{task_id}/responses", json=decision
        )
        assert decision_response.status_code == 200, decision_response.text
        assert decision_response.json()["data"]["result"]["human_task_status"] == "modified"

        final_task = client.get(f"/api/v1/human-tasks/{task_id}").json()["data"]
        assert final_task["status"] == "modified"

print("SMOKE TEST PASSED")
