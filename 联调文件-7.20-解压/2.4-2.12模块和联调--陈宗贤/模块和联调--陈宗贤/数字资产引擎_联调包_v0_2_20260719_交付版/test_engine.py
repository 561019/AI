# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

try:
    from engine import DigitalAssetEngine, EngineError
    import server as server_module
except ImportError:  # 兼容从上级目录执行 unittest discover
    from digital_asset_engine_demo.engine import DigitalAssetEngine, EngineError
    from digital_asset_engine_demo import server as server_module


class DigitalAssetEngineSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = DigitalAssetEngine(Path(self.tmp.name) / "test.db", seed_demo=False)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def create(self, actor: str = "tester_a", asset_type: str = "skill", scope: str = "personal", **extra) -> dict:
        config = extra.pop("config", {})
        if asset_type == "skill":
            config = {
                "tool_id": "fermentation_anomaly_checker",
                "tool_version": "1.0.0",
                **config,
            }
        payload = {
            "asset_type": asset_type,
            "asset_name": extra.pop("asset_name", "发酵异常识别技能"),
            "description": extra.pop("description", "登记固定工具引用，不在引擎内执行计算"),
            "scope": scope,
            "config": config,
            **extra,
        }
        asset = self.engine.create_asset(actor, payload)
        if asset_type == "skill":
            self.engine.validate_skill(actor, asset["asset_id"])
            for role, model_id, value in (
                ("primary", "model-main", 0.95),
                ("backup", "model-backup", 0.90),
            ):
                self.engine.register_skill_model_evaluation(actor, asset["asset_id"], {
                    "model_role": role,
                    "model_id": model_id,
                    "model_version": "1.0.0",
                    "dataset_ref": "dataset://fixed-evaluation/v1",
                    "metric_name": "accuracy",
                    "metric_value": value,
                    "conclusion": "passed",
                    "report_ref": f"report://{model_id}/v1",
                })
        return asset

    def test_personal_asset_is_only_visible_to_owner(self) -> None:
        asset = self.create("tester_a")
        self.assertEqual([a["asset_id"] for a in self.engine.state("tester_a")["assets"]], [asset["asset_id"]])
        self.assertEqual(self.engine.state("tester_b")["assets"], [])
        with self.assertRaises(EngineError) as ctx:
            self.engine.get_asset_for_actor("tester_b", asset["asset_id"])
        self.assertEqual(ctx.exception.code, "NO_READ_PERMISSION")
        self.assertEqual(self.engine.state("tester_b")["assets"], [])
        self.assertGreaterEqual(self.engine.state("tester_b")["stats"]["denyCount"], 1)

    def test_platform_operator_only_sees_redacted_metadata_and_cannot_mutate(self) -> None:
        asset = self.create("tester_a", config={"secret": "business-content"})
        item = next(a for a in self.engine.state("engine_admin")["assets"] if a["asset_id"] == asset["asset_id"])
        self.assertTrue(item["metadataOnly"])
        self.assertTrue(item["redacted"])
        self.assertEqual(item["asset_name"], "受限业务资产")
        self.assertEqual(item["config"], {})
        self.assertTrue(item["capabilities"]["viewMetadata"])
        self.assertFalse(item["capabilities"]["viewContent"])
        self.assertFalse(any(item["capabilities"][key] for key in (
            "modify", "activatePersonal", "submitAdoption", "submitPublish", "disable", "deleteDraft", "addSource"
        )))
        with self.assertRaises(EngineError) as ctx:
            self.engine.update_asset("engine_admin", asset["asset_id"], {"description": "越权"})
        self.assertEqual(ctx.exception.code, "NO_UPDATE_PERMISSION")

    def test_personal_activation_is_not_publication(self) -> None:
        asset = self.create()
        active = self.engine.activate_personal("tester_a", asset["asset_id"])
        self.assertEqual(active["status"], "personal_active")
        self.assertEqual(active["scope"], "personal")
        self.assertEqual(self.engine.state("tester_b")["assets"], [])
        owner_item = self.engine.get_asset_for_actor("tester_a", asset["asset_id"])
        self.assertTrue(owner_item["resourceCallable"])

    def test_adoption_keeps_source_as_adopted_archive_and_creates_derived_department_draft(self) -> None:
        source = self.create(config={"tool_ref": "fixed_checker_v1"})
        self.engine.activate_personal("tester_a", source["asset_id"])
        workflow = self.engine.submit_adoption("tester_a", source["asset_id"], {"reason": "部门复用"})
        self.assertNotEqual(workflow["submitter_id"], workflow["approver_id"])

        reviewer_item = self.engine.get_asset_for_actor(workflow["approver_id"], source["asset_id"])
        self.assertTrue(reviewer_item["permissionDecision"]["viewContent"])
        self.assertTrue(reviewer_item["capabilities"]["reviewAssignedWorkflow"])
        self.assertFalse(reviewer_item["capabilities"]["modify"])

        with self.assertRaises(EngineError) as ctx:
            self.engine.approve_workflow("tester_a", workflow["workflow_id"])
        self.assertEqual(ctx.exception.code, "NO_WORKFLOW_APPROVAL_PERMISSION")

        approved = self.engine.approve_workflow(workflow["approver_id"], workflow["workflow_id"])
        derived = approved["result_asset"]
        source_after = self.engine.get_asset_for_actor("tester_a", source["asset_id"])
        self.assertEqual(source_after["status"], "adopted")
        self.assertEqual(source_after["scope"], "personal")
        self.assertFalse(source_after["resourceCallable"])
        self.assertEqual(derived["scope"], "department")
        self.assertEqual(derived["status"], "draft")
        self.assertEqual(derived["derived_from_asset_id"], source["asset_id"])
        self.assertEqual(derived["creator_id"], "tester_a")
        self.assertEqual(derived["contributor_id"], "tester_a")
        self.assertEqual(derived["maintainer_id"], workflow["approver_id"])

    def test_department_publish_is_pending_and_requires_another_fixed_approver(self) -> None:
        asset = self.create("tester_b", scope="department")
        workflow = self.engine.submit_publish("tester_b", asset["asset_id"])
        pending = self.engine.get_asset_for_actor("tester_b", asset["asset_id"])
        self.assertEqual(pending["status"], "pending_publish")
        self.assertNotEqual(workflow["submitter_id"], workflow["approver_id"])
        self.assertEqual(workflow["approval_position"], "部门数字资产审批岗位")

        with self.assertRaises(EngineError):
            self.engine.approve_workflow("tester_b", workflow["workflow_id"])
        approved = self.engine.approve_workflow(workflow["approver_id"], workflow["workflow_id"])
        self.assertEqual(approved["result_asset"]["status"], "published")
        self.assertEqual(approved["result_asset"]["scope"], "department")

    def test_company_publish_is_pending_and_submitter_cannot_self_approve(self) -> None:
        asset = self.create("u_company_approver", asset_type="skill", scope="company")
        workflow = self.engine.submit_publish("u_company_approver", asset["asset_id"])
        self.assertEqual(workflow["approval_position"], "公司数字资产审批岗位")
        self.assertEqual(workflow["approver_id"], "u_company_approver_2")
        with self.assertRaises(EngineError) as ctx:
            self.engine.approve_workflow("u_company_approver", workflow["workflow_id"])
        self.assertEqual(ctx.exception.code, "NO_WORKFLOW_APPROVAL_PERMISSION")
        published = self.engine.approve_workflow("u_company_approver_2", workflow["workflow_id"])
        self.assertEqual(published["result_asset"]["status"], "published")

    def test_registry_never_returns_business_data_permission(self) -> None:
        asset = self.create("tester_b", scope="department", config={"tool_ref": "fixed_v1"})
        workflow = self.engine.submit_publish("tester_b", asset["asset_id"])
        self.engine.approve_workflow(workflow["approver_id"], workflow["workflow_id"])
        member_item = self.engine.get_asset_for_actor("u_staff", asset["asset_id"])
        self.assertTrue(member_item["resourceCallable"])
        self.assertNotIn("dataReadable", member_item)
        self.assertIn("permissionDecision", member_item)
        self.assertEqual(member_item["permissionDecision"]["adapter"], "L1 权限管理 Mock")

    def test_tags_and_data_access_config_cannot_grant_permission(self) -> None:
        asset = self.create(
            "tester_a", scope="personal",
            tags=[{"key": "authorized_department", "value": "行政部"}],
            config={"data_access": {"departments": ["行政部"]}},
        )
        with self.assertRaises(EngineError) as ctx:
            self.engine.get_asset_for_actor("tester_c", asset["asset_id"])
        self.assertEqual(ctx.exception.code, "NO_READ_PERMISSION")

    def test_disabled_asset_blocks_every_later_change(self) -> None:
        asset = self.create()
        self.engine.activate_personal("tester_a", asset["asset_id"])
        disabled = self.engine.disable_asset("tester_a", asset["asset_id"], {"reason": "停止使用"})
        self.assertEqual(disabled["status"], "disabled")
        attempts = [
            lambda: self.engine.update_asset("tester_a", asset["asset_id"], {"description": "x"}),
            lambda: self.engine.submit_adoption("tester_a", asset["asset_id"]),
            lambda: self.engine.disable_asset("tester_a", asset["asset_id"]),
        ]
        for attempt in attempts:
            with self.assertRaises(EngineError) as ctx:
                attempt()
            self.assertEqual(ctx.exception.code, "ASSET_DISABLED")

    def test_only_owner_can_logically_delete_personal_draft(self) -> None:
        asset = self.create()
        with self.assertRaises(EngineError) as ctx:
            self.engine.delete_draft("tester_b", asset["asset_id"])
        self.assertIn(ctx.exception.code, {"NO_DELETE_DRAFT_PERMISSION", "NO_READ_PERMISSION"})
        deleted = self.engine.delete_draft("tester_a", asset["asset_id"])
        self.assertEqual(deleted["status"], "deleted")
        self.assertGreaterEqual(deleted["current_version"], 2)

    def test_knowledge_source_is_registered_and_parser_result_is_external(self) -> None:
        kb = self.create("tester_a", asset_type="knowledge_base")
        source = self.engine.add_source("tester_a", kb["asset_id"], {"file_name": "发酵规程.docx"})
        self.assertEqual(source["parse_status"], "pending")
        parsed = self.engine.parse_source("tester_a", source["source_id"], {"outcome": "success"})
        self.assertEqual(parsed["parse_status"], "success")
        self.assertIn("不执行真实解析", parsed["parse_result"]["note"])
        skill = self.create("tester_a", asset_type="skill", asset_name="不是容器")
        with self.assertRaises(EngineError) as ctx:
            self.engine.add_source("tester_a", skill["asset_id"], {"file_name": "x.docx"})
        self.assertEqual(ctx.exception.code, "SOURCE_REQUIRES_KB")

    def test_only_three_asset_types_and_material_is_rejected(self) -> None:
        with self.assertRaises(EngineError) as ctx:
            self.create("tester_a", asset_type="material", asset_name="错误的第四类资产")
        self.assertEqual(ctx.exception.code, "BAD_ASSET_TYPE")

    def test_knowledge_source_upload_stores_original_and_parser_remains_external(self) -> None:
        kb = self.create("tester_a", asset_type="knowledge_base", asset_name="工艺知识库")
        content = b"knowledge-source-content"
        source = self.engine.upload_knowledge_source("tester_a", kb["asset_id"], {
            "file_name": "fermentation-process.pdf",
            "content_type": "application/pdf",
            "data_base64": base64.b64encode(content).decode("ascii"),
            "description": "发酵工艺资料",
        })
        self.assertEqual(source["parse_status"], "pending")
        self.assertEqual(source["storage_status"], "registered")
        self.assertEqual(source["size_bytes"], len(content))
        download = self.engine.knowledge_source_for_download("tester_a", source["source_id"])
        self.assertEqual(Path(download["storage_path"]).read_bytes(), content)
        parsed = self.engine.parse_source("tester_a", source["source_id"], {"outcome": "success"})
        self.assertEqual(parsed["parse_status"], "success")
        self.assertIn("不执行真实解析", parsed["parse_result"]["note"])
        with self.assertRaises(EngineError) as ctx:
            self.engine.knowledge_source_for_download("tester_b", source["source_id"])
        self.assertEqual(ctx.exception.code, "NO_KNOWLEDGE_SOURCE_DOWNLOAD_PERMISSION")

    def test_personal_agent_validates_entry_skill_and_kb_dependencies(self) -> None:
        skill = self.create("tester_a", asset_name="个人发酵检查技能")
        self.engine.activate_personal("tester_a", skill["asset_id"])
        kb = self.create("tester_a", asset_type="knowledge_base", asset_name="个人工艺知识库")
        source = self.engine.add_source("tester_a", kb["asset_id"], {"file_name": "个人工艺规程.docx"})
        self.engine.parse_source("tester_a", source["source_id"], {"outcome": "success"})
        with self.assertRaises(EngineError) as ctx:
            self.engine.activate_personal("tester_a", kb["asset_id"])
        self.assertEqual(ctx.exception.code, "L1_KB_NOT_READY")
        binding = self.engine.request_l1_knowledge_base("tester_a", kb["asset_id"])
        with self.assertRaises(EngineError) as ctx:
            self.engine.register_l1_knowledge_base("tester_a", binding["binding_id"], {
                "l1_kb_id": "l1kb_personal", "namespace": "test.personal", "outcome": "ready",
            })
        self.assertEqual(ctx.exception.code, "NO_L1_KB_CALLBACK_PERMISSION")
        self.engine.register_l1_knowledge_base("engine_admin", binding["binding_id"], {
            "l1_kb_id": "l1kb_personal", "namespace": "test.personal", "outcome": "ready", "callback_mode": "mock",
        })
        with self.assertRaises(EngineError) as ctx:
            self.engine.register_source_index("tester_a", source["source_id"], {
                "outcome": "indexed", "chunk_count": 4, "vector_count": 4,
            })
        self.assertEqual(ctx.exception.code, "NO_INDEX_CALLBACK_PERMISSION")
        self.engine.register_source_index("engine_admin", source["source_id"], {
            "outcome": "indexed", "chunk_count": 4, "vector_count": 4,
            "index_version": "test-v1", "callback_mode": "mock",
        })
        self.engine.activate_personal("tester_a", kb["asset_id"])
        agent = self.create(
            "tester_a", asset_type="agent", asset_name="个人巡检Agent",
            config={
                "skill_ids": [skill["asset_id"]], "entry_skill_id": skill["asset_id"],
                "knowledge_base_ids": [kb["asset_id"]],
            },
        )
        activated = self.engine.activate_personal("tester_a", agent["asset_id"])
        self.assertEqual(activated["status"], "personal_active")
        execution = self.engine.execute_agent("tester_a", agent["asset_id"], {
            "input": {"temperature_c": 30, "ph": 6.5, "dissolved_oxygen_pct": 35},
        })
        self.assertEqual(execution["skill_asset_id"], skill["asset_id"])

    def test_real_l4_capability_request_reuses_one_trace_through_agent_and_tool(self) -> None:
        seeded = DigitalAssetEngine(Path(self.tmp.name) / "real_l4.db", seed_demo=True)
        result = seeded.execute_l4_capability("tester_a", {
            "source_layer": "L4", "target_asset_id": "asset_demo_fermentation_agent",
            "request_text": "检查当前发酵批次",
            "input": {"temperature_c": 34, "ph": 6.5, "dissolved_oxygen_pct": 12},
        })
        self.assertEqual(result["output"]["abnormal_count"], 2)
        self.assertEqual(result["standard_response"]["code"], "EXECUTION_SUCCEEDED")
        self.assertEqual(result["trace_id"], result["standard_response"]["trace_id"])
        self.assertTrue(any(step["component"] == "功能登记库" for step in result["l4_route"]))
        state = seeded.state("tester_a")
        call = next(item for item in state["l4Requests"] if item["request_id"] == result["request_id"])
        self.assertEqual(call["trace_id"], result["trace_id"])
        with self.assertRaises(EngineError) as ctx:
            seeded.execute_l4_capability("tester_c", {
                "source_layer": "L4", "target_asset_id": "asset_demo_fermentation_agent",
                "input": {"temperature_c": 30, "ph": 6.5, "dissolved_oxygen_pct": 35},
            })
        self.assertEqual(ctx.exception.code, "NO_AGENT_CALL_PERMISSION")

    def test_success_and_denial_are_both_audited_and_versions_are_retained(self) -> None:
        asset = self.create()
        self.engine.update_asset("tester_a", asset["asset_id"], {"description": "第二版"})
        with self.assertRaises(EngineError):
            self.engine.update_asset("tester_b", asset["asset_id"], {"description": "越权"})
        owner_state = self.engine.state("tester_a")
        versions = [v for v in owner_state["versions"] if v["asset_id"] == asset["asset_id"]]
        self.assertGreaterEqual(len(versions), 2)
        raw_logs = []
        with closing_connection(self.engine.connect()) as conn:
            raw_logs = list(conn.execute("SELECT * FROM audit_log WHERE asset_id=?", (asset["asset_id"],)))
        self.assertIn("ALLOW", {row["decision_result"] for row in raw_logs})
        self.assertIn("DENY", {row["decision_result"] for row in raw_logs})

    def test_workspace_read_audit_is_lightweight_and_never_embeds_prior_logs(self) -> None:
        """读取工作台可留痕，但不能把完整 state（尤其是 logs）递归写回数据库。"""
        self.create()
        for _ in range(3):
            self.engine.state("tester_a")
        with closing_connection(self.engine.connect()) as conn:
            rows = list(conn.execute(
                "SELECT asset_after FROM audit_log WHERE action='read_state' ORDER BY created_at"
            ))
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertLess(len(row["asset_after"]), 500)
            summary = json.loads(row["asset_after"])
            self.assertEqual(summary["kind"], "workspace_read")
            self.assertNotIn("logs", summary)

    def test_l4_build_kb_returns_accepted_trace_and_does_not_fake_parsing(self) -> None:
        seeded = DigitalAssetEngine(Path(self.tmp.name) / "l4_build.db", seed_demo=True)
        result = seeded.invoke_l4_scenario("tester_b", {
            "scenario_code": "build_process_kb",
            "request_mode": "natural_language",
            "request_text": "把发酵工艺资料建设成知识库",
            "source_layer": "L4",
        })
        self.assertEqual(result["response_type"], "accepted")
        self.assertEqual(result["standard_response"]["type"], "accepted")
        self.assertTrue(result["standard_response"]["callback_expected"])
        self.assertTrue(result["trace_id"].startswith("trace_"))
        self.assertEqual(result["resolved_asset"]["asset_id"], "asset_demo_l4_kb_draft")
        self.assertIn("不执行真实", result["execution_boundary"])
        self.assertTrue(any("意图分析引擎" in step["component"] for step in result["route"]))
        self.assertTrue(any(call["request_id"] == result["request_id"] for call in seeded.state("tester_b")["l4Requests"]))

    def test_l4_runtime_resolution_separates_resource_and_data_permissions(self) -> None:
        seeded = DigitalAssetEngine(Path(self.tmp.name) / "l4_use.db", seed_demo=True)
        allowed = seeded.invoke_l4_scenario("tester_a", {
            "scenario_code": "use_fermentation_skill", "source_layer": "L4",
        })
        self.assertEqual(allowed["response_type"], "immediate")
        self.assertTrue(allowed["decisions"]["resourceCallable"]["allowed"])
        self.assertTrue(allowed["decisions"]["businessDataBoundary"]["allowed"])

        outsider = seeded.invoke_l4_scenario("tester_c", {
            "scenario_code": "use_fermentation_skill", "source_layer": "L4",
        })
        self.assertEqual(outsider["response_type"], "rejected")
        self.assertEqual(outsider["decision_code"], "RESOURCE_PERMISSION_DENIED")
        self.assertIsNone(outsider["resolved_asset"])

        agent_allowed = seeded.invoke_l4_scenario("tester_a", {
            "scenario_code": "use_company_agent", "source_layer": "L4",
        })
        self.assertEqual(agent_allowed["response_type"], "immediate")
        self.assertTrue(agent_allowed["decisions"]["resourceCallable"]["allowed"])
        self.assertTrue(agent_allowed["decisions"]["businessDataBoundary"]["allowed"])

        outsider_agent = seeded.invoke_l4_scenario("tester_c", {
            "scenario_code": "use_company_agent", "source_layer": "L4",
        })
        self.assertEqual(outsider_agent["response_type"], "rejected")
        self.assertEqual(outsider_agent["decision_code"], "RESOURCE_PERMISSION_DENIED")

    def test_l4_capability_gap_returns_confirmation_without_reading_business_data(self) -> None:
        seeded = DigitalAssetEngine(Path(self.tmp.name) / "l4_gap.db", seed_demo=True)
        result = seeded.invoke_l4_scenario("tester_a", {
            "source_layer": "L4",
            "scenario_code": "commission_skill_gap",
            "request_mode": "natural_language",
            "request_text": "帮我计算 2026 年 6 月销售提成。",
        })
        self.assertEqual(result["response_type"], "accepted")
        self.assertEqual(result["decision_code"], "CAPABILITY_GAP_CONFIRM_REQUIRED")
        self.assertIsNone(result["resolved_asset"])
        self.assertIn("不读取销售额", result["decisions"]["businessDataBoundary"]["reason"])
        self.assertTrue(any(step["component"] == "规则计算引擎" for step in result["route"]))
        self.assertTrue(any(step["component"] == "数字资产引擎" for step in result["route"]))

    def test_standard_flow_envelope_queries_registry_and_replays_idempotently(self) -> None:
        seeded = DigitalAssetEngine(Path(self.tmp.name) / "flow_query.db", seed_demo=True)
        envelope = {
            "protocol_version": "1.0", "message_id": "msg_flow_query", "trace_id": "trace_flow_query",
            "request_id": "req_flow_query", "parent_message_id": "msg_parent_flow_query",
            "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
            "target": {"layer": "L2", "service_code": "l2.digital_asset"},
            "channel": "l2_internal", "route_type": "task.dispatch", "action": "asset.query",
            "capability_id": "CAP.DIGITAL_ASSET.ASSET_QUERY",
            "capability_dictionary_version": "test_1", "registry_version": "test_registry_1",
            "idempotency_key": "idem_flow_query", "deadline_at": "2099-12-31T23:59:59+08:00",
            "actor": {"person_id": "tester_a", "tenant_id": "demo"},
            "context": {"workflow_instance_id": "wf_flow_query", "node_id": "node_flow_query", "task_id": "task_flow_query", "data_refs": []},
            "payload": {"asset_id": "asset_demo_executable_skill"},
        }
        receipt = seeded.process_flow_task("tester_a", envelope)
        self.assertEqual(receipt["code"], "FLOW_TASK_SUCCEEDED")
        self.assertEqual(receipt["reply_type"], "success")
        self.assertEqual(receipt["service_code"], "l2.digital_asset.asset.query")
        self.assertEqual(receipt["result"]["count"], 1)
        replay = seeded.process_flow_task("tester_a", envelope)
        self.assertTrue(replay["idempotent_replay"])

    def test_standard_flow_envelope_rejects_missing_protocol_fields(self) -> None:
        seeded = DigitalAssetEngine(Path(self.tmp.name) / "flow_invalid.db", seed_demo=True)
        with self.assertRaises(EngineError) as captured:
            seeded.process_flow_task("tester_a", {
                "trace_id": "trace_incomplete",
                "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
                "target": {"layer": "L2", "service_code": "l2.digital_asset"},
                "action": "asset.query",
            })
        self.assertEqual(captured.exception.code, "MISSING_FLOW_ENVELOPE_FIELD")

    def test_standard_flow_envelope_registers_knowledge_source_result(self) -> None:
        seeded = DigitalAssetEngine(Path(self.tmp.name) / "flow_source.db", seed_demo=True)

        def envelope(action: str, actor: str, task: str, payload: dict) -> dict:
            return {
                "protocol_version": "1.0", "message_id": f"msg_{task}", "trace_id": f"trace_{task}",
                "request_id": f"req_{task}", "parent_message_id": f"msg_parent_{task}",
                "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
                "target": {"layer": "L2", "service_code": "l2.digital_asset"},
                "channel": "l2_internal", "route_type": "task.dispatch", "action": action,
                "capability_id": f"CAP.DIGITAL_ASSET.{action.upper().replace('.', '_')}",
                "capability_dictionary_version": "test_1", "registry_version": "test_registry_1",
                "idempotency_key": f"idem_{task}", "deadline_at": "2099-12-31T23:59:59+08:00",
                "actor": {"person_id": actor, "tenant_id": "demo"},
                "context": {"workflow_instance_id": f"wf_{task}", "node_id": f"node_{task}", "task_id": f"task_{task}", "data_refs": []},
                "payload": payload,
            }

        created = seeded.process_flow_task("tester_a", envelope("asset.create", "tester_a", "kb", {
            "asset_type": "knowledge_base", "asset_name": "联调知识库", "scope": "personal",
            "description": "用于测试流程执行引擎转交的知识源回执",
        }))
        asset_id = created["result"]["asset_id"]
        source_receipt = seeded.process_flow_task("tester_a", envelope("knowledge_source.register", "tester_a", "source", {
            "knowledge_base_ref": asset_id, "artifact_ref": "minio://demo/commission-policy-v1.pdf",
            "source_type": "document", "source_description": "正式制度原件引用",
        }))
        self.assertEqual(source_receipt["reply_type"], "accepted")
        self.assertTrue(source_receipt["callback_expected"])
        source_id = source_receipt["result"]["source_id"]
        result_payload = {
            "source_id": source_id, "processing_status": "success", "parser_task_ref": "parser_task_001",
            "knowledge_ref": "knowledge_ref_001", "index_ref": "index_ref_001", "result_summary": "解析完成",
            "parent_task_id": "task_source", "artifact_ref": "minio://demo/commission-policy-v1.pdf",
        }
        # 异步回执必须沿用原登记任务的 trace_id，而不是重新开一条链路。
        result_envelope = envelope("knowledge_source.result.register", "engine_admin", "result", result_payload)
        result_envelope["trace_id"] = "trace_source"
        result_receipt = seeded.process_flow_task("engine_admin", result_envelope)
        self.assertEqual(result_receipt["result"]["parse_status"], "success")
        self.assertEqual(result_receipt["result"]["parse_result"]["index_ref"], "index_ref_001")

    def test_text_only_skill_cannot_be_activated(self) -> None:
        asset = self.engine.create_asset("tester_a", {
            "asset_type": "skill", "asset_name": "只有文字的技能",
            "description": "没有固定工具绑定", "scope": "personal", "config": {},
        })
        self.assertEqual(asset["config"]["lifecycle_stage"], "requirement_draft")
        visible = self.engine.get_asset_for_actor("tester_a", asset["asset_id"])
        self.assertTrue(visible["capabilities"]["bindSkillImplementation"])
        self.assertFalse(visible["capabilities"]["validateSkill"])
        self.assertFalse(visible["capabilities"]["activatePersonal"])
        with self.assertRaises(EngineError) as ctx:
            self.engine.activate_personal("tester_a", asset["asset_id"])
        self.assertEqual(ctx.exception.code, "SKILL_TOOL_NOT_BOUND")

    def test_skill_requirement_can_bind_implementation_then_validate(self) -> None:
        asset = self.engine.create_asset("tester_a", {
            "asset_type": "skill",
            "asset_name": "批次异常检查研发需求",
            "description": "先登记输入输出和验收标准，再绑定实现",
            "scope": "personal",
            "config": {
                "candidate_source": "evolution",
                "requirement": {
                    "input_definition": "温度、pH、溶氧",
                    "output_definition": "异常项和证据",
                    "acceptance_criteria": "固定测试全部通过",
                },
            },
        })
        bound = self.engine.bind_skill_implementation("tester_a", asset["asset_id"], {
            "tool_id": "fermentation_anomaly_checker",
            "tool_version": "1.0.0",
        })
        self.assertEqual(bound["config"]["lifecycle_stage"], "implementation_bound")
        self.assertEqual(bound["config"]["validation_status"], "not_validated")
        before_test = self.engine.get_asset_for_actor("tester_a", asset["asset_id"])
        self.assertTrue(before_test["capabilities"]["validateSkill"])
        self.assertFalse(before_test["capabilities"]["activatePersonal"])

        self.engine.validate_skill("tester_a", asset["asset_id"])
        for role in ("primary", "backup"):
            self.engine.register_skill_model_evaluation("tester_a", asset["asset_id"], {
                "model_role": role, "model_id": f"model-{role}", "model_version": "1.0.0",
                "dataset_ref": "dataset://fixed/v1", "metric_name": "accuracy",
                "metric_value": 0.9, "conclusion": "passed",
            })
        after_test = self.engine.get_asset_for_actor("tester_a", asset["asset_id"])
        self.assertEqual(after_test["config"]["lifecycle_stage"], "validation_passed")
        self.assertTrue(after_test["capabilities"]["activatePersonal"])

    def test_skill_development_request_candidate_binding_and_validation_are_separate_steps(self) -> None:
        asset = self.engine.create_asset("tester_a", {
            "asset_type": "skill",
            "asset_name": "发酵参数异常检查 Skill 研发需求",
            "description": "先提交研发，再接收候选实现，最后绑定和测试",
            "scope": "personal",
            "config": {
                "candidate_source": "evolution",
                "requirement": {
                    "input_definition": "温度、pH、溶氧和批次编号",
                    "output_definition": "异常项、证据和风险等级",
                    "acceptance_criteria": "固定测试全部通过且高风险结果要求真人确认",
                },
            },
        })
        development = self.engine.submit_skill_development("tester_a", asset["asset_id"])
        self.assertEqual(development["status"], "submitted")
        self.assertEqual(development["target_system"], "L1进化机制")

        locked = self.engine.get_asset_for_actor("tester_a", asset["asset_id"])
        self.assertEqual(locked["config"]["lifecycle_stage"], "development_submitted")
        self.assertFalse(locked["capabilities"]["modify"])
        self.assertFalse(locked["capabilities"]["bindSkillImplementation"])
        self.assertFalse(locked["capabilities"]["activatePersonal"])
        self.assertFalse(locked["capabilities"]["deleteDraft"])
        with self.assertRaises(EngineError) as ctx:
            self.engine.delete_draft("tester_a", asset["asset_id"])
        self.assertEqual(ctx.exception.code, "NO_DELETE_DRAFT_PERMISSION")

        with self.assertRaises(EngineError) as ctx:
            self.engine.register_skill_candidate("tester_a", development["development_id"], {
                "tool_id": "fermentation_anomaly_checker", "tool_version": "1.0.0",
            })
        self.assertEqual(ctx.exception.code, "NO_CANDIDATE_CALLBACK_PERMISSION")
        with self.assertRaises(EngineError) as ctx:
            self.engine.register_skill_candidate("engine_admin", development["development_id"], {
                "tool_id": "unregistered_candidate", "tool_version": "0.1.0",
            })
        self.assertEqual(ctx.exception.code, "CANDIDATE_TOOL_NOT_REGISTERED")

        candidate = self.engine.register_skill_candidate("engine_admin", development["development_id"], {
            "tool_id": "fermentation_anomaly_checker",
            "tool_version": "1.0.0",
            "callback_mode": "mock",
            "artifact_uri": "registry://skills/fermentation-anomaly-checker/1.0.0",
            "test_report_uri": "report://skills/fermentation-anomaly-checker/1.0.0",
        })
        self.assertEqual(candidate["status"], "ready_to_bind")
        ready = self.engine.get_asset_for_actor("tester_a", asset["asset_id"])
        self.assertEqual(ready["config"]["lifecycle_stage"], "candidate_ready")
        self.assertTrue(ready["capabilities"]["bindSkillImplementation"])

        platform_state = self.engine.state("engine_admin")
        platform_request = next(
            item for item in platform_state["developmentRequests"]
            if item["development_id"] == development["development_id"]
        )
        self.assertTrue(platform_request["metadataOnly"])
        self.assertEqual(platform_request["requirement"], {})
        self.assertFalse(platform_request["capabilities"]["registerCandidate"])

        bound = self.engine.bind_skill_implementation("tester_a", asset["asset_id"], {
            "tool_id": candidate["candidate_tool_id"],
            "tool_version": candidate["candidate_tool_version"],
        })
        self.assertEqual(bound["config"]["lifecycle_stage"], "implementation_bound")
        owner_request = next(
            item for item in self.engine.state("tester_a")["developmentRequests"]
            if item["development_id"] == development["development_id"]
        )
        self.assertEqual(owner_request["status"], "bound")

        validation = self.engine.validate_skill("tester_a", asset["asset_id"])
        self.assertEqual(validation["status"], "passed")
        validated = self.engine.get_asset_for_actor("tester_a", asset["asset_id"])
        self.assertEqual(validated["config"]["lifecycle_stage"], "validation_passed")

    def test_incomplete_skill_requirement_cannot_be_submitted_for_development(self) -> None:
        asset = self.engine.create_asset("tester_a", {
            "asset_type": "skill",
            "asset_name": "不完整 Skill 需求",
            "description": "缺少输出和验收标准",
            "scope": "personal",
            "config": {
                "candidate_source": "developer",
                "requirement": {"input_definition": "批次号"},
            },
        })
        with self.assertRaises(EngineError) as ctx:
            self.engine.submit_skill_development("tester_a", asset["asset_id"])
        self.assertEqual(ctx.exception.code, "INCOMPLETE_SKILL_REQUIREMENT")

    def test_general_update_cannot_smuggle_skill_tool_binding(self) -> None:
        asset = self.engine.create_asset("tester_a", {
            "asset_type": "skill", "asset_name": "未分派研发需求",
            "description": "普通修改接口不得偷换实现", "scope": "personal", "config": {},
        })
        updated = self.engine.update_asset("tester_a", asset["asset_id"], {
            "config": {
                "tool_id": "fermentation_anomaly_checker",
                "tool_version": "1.0.0",
                "validation_status": "passed",
            },
            "change_summary": "尝试绕过绑定接口",
        })
        self.assertNotIn("tool_id", updated["config"])
        self.assertEqual(updated["config"]["lifecycle_stage"], "requirement_draft")
        with self.assertRaises(EngineError) as ctx:
            self.engine.activate_personal("tester_a", asset["asset_id"])
        self.assertEqual(ctx.exception.code, "SKILL_TOOL_NOT_BOUND")

    def test_unknown_skill_implementation_cannot_be_bound(self) -> None:
        asset = self.engine.create_asset("tester_a", {
            "asset_type": "skill", "asset_name": "未知实现测试",
            "description": "只能绑定固定工具登记库中的实现", "scope": "personal", "config": {},
        })
        with self.assertRaises(EngineError) as ctx:
            self.engine.bind_skill_implementation("tester_a", asset["asset_id"], {
                "tool_id": "free_text_python",
                "tool_version": "latest",
            })
        self.assertEqual(ctx.exception.code, "SKILL_TOOL_UNAVAILABLE")

    def test_skill_executes_fixed_tool_and_requires_human_confirmation(self) -> None:
        asset = self.create("tester_a")
        self.engine.activate_personal("tester_a", asset["asset_id"])
        execution = self.engine.execute_skill("tester_a", asset["asset_id"], {
            "input": {"temperature_c": 34, "ph": 6.5, "dissolved_oxygen_pct": 12},
        })
        self.assertEqual(execution["output"]["conclusion"], "abnormal")
        self.assertEqual(execution["output"]["abnormal_count"], 2)
        self.assertEqual(execution["tool_version"], "1.0.0")
        self.assertEqual(execution["confirmation_status"], "pending")
        with self.assertRaises(EngineError) as ctx:
            self.engine.confirm_execution("tester_b", execution["execution_id"])
        self.assertEqual(ctx.exception.code, "NO_EXECUTION_CONFIRM_PERMISSION")
        confirmed = self.engine.confirm_execution("tester_a", execution["execution_id"])
        self.assertEqual(confirmed["confirmation_status"], "confirmed")

    def test_published_agent_orchestrates_published_skill(self) -> None:
        seeded = DigitalAssetEngine(Path(self.tmp.name) / "runtime.db", seed_demo=True)
        execution = seeded.execute_agent("tester_a", "asset_demo_fermentation_agent", {
            "input": {"temperature_c": 30, "ph": 6.5, "dissolved_oxygen_pct": 35},
        })
        self.assertEqual(execution["agent_asset_id"], "asset_demo_fermentation_agent")
        self.assertEqual(execution["skill_asset_id"], "asset_demo_executable_skill")
        self.assertEqual(execution["output"]["conclusion"], "normal")
        self.assertEqual(execution["confirmation_status"], "not_required")
        with self.assertRaises(EngineError) as ctx:
            seeded.execute_agent("tester_c", "asset_demo_fermentation_agent", {
                "input": {"temperature_c": 30, "ph": 6.5, "dissolved_oxygen_pct": 35},
            })
        self.assertEqual(ctx.exception.code, "NO_AGENT_CALL_PERMISSION")

    def test_l4_entry_rejects_non_l4_source(self) -> None:
        seeded = DigitalAssetEngine(Path(self.tmp.name) / "l4_source.db", seed_demo=True)
        with self.assertRaises(EngineError) as ctx:
            seeded.invoke_l4_scenario("tester_a", {
                "scenario_code": "use_fermentation_skill", "source_layer": "L3",
            })
        self.assertEqual(ctx.exception.code, "SOURCE_LAYER_NOT_ALLOWED")

    def test_demo_seed_and_reset_restore_governance_scenarios(self) -> None:
        seeded = DigitalAssetEngine(Path(self.tmp.name) / "seeded.db", seed_demo=True)
        state = seeded.state("tester_a")
        self.assertGreaterEqual(state["stats"]["visibleAssetCount"], 4)
        company = next(a for a in state["assets"] if a["asset_id"] == "asset_demo_company")
        self.assertTrue(company["resourceCallable"])
        self.assertNotIn("dataReadable", company)
        self.assertIn("permissionDecision", company)
        seeded.reset_demo("engine_admin")
        restored = seeded.state("tester_a")
        self.assertTrue(any(a["asset_id"] == "asset_demo_kb" for a in restored["assets"]))
        self.assertTrue(any(s["source_id"] == "src_demo_kb" for s in restored["sources"]))
        maintainer_state = seeded.state("tester_b")
        source_draft = next(a for a in maintainer_state["assets"] if a["asset_id"] == "asset_demo_kb_draft")
        self.assertTrue(source_draft["capabilities"]["addSource"])
        l4_draft = next(a for a in maintainer_state["assets"] if a["asset_id"] == "asset_demo_l4_kb_draft")
        self.assertTrue(l4_draft["capabilities"]["addSource"])


class closing_connection:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *_args):
        self.conn.close()


class HttpApiIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_engine = server_module.ENGINE
        server_module.ENGINE = DigitalAssetEngine(Path(self.tmp.name) / "api.db", seed_demo=False)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_module.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server_module.ENGINE = self.old_engine
        self.tmp.cleanup()

    def request_json(self, path: str, *, method: str = "GET", body: dict | None = None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_state_requires_explicit_actor(self) -> None:
        status, body = self.request_json("/api/state")
        self.assertEqual(status, 401)
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "ACTOR_REQUIRED")
        status, body = self.request_json("/api/state?actor=tester_a")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["currentActor"]["userId"], "tester_a")

    def test_http_standard_flow_task_accepts_actor_envelope_and_replays(self) -> None:
        envelope = {
            "protocol_version": "1.0", "message_id": "msg_http_flow_query_001",
            "trace_id": "trace_http_flow_query_001", "request_id": "req_http_flow_query_001",
            "parent_message_id": "msg_parent_http_flow_query_001",
            "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
            "target": {"layer": "L2", "service_code": "l2.digital_asset"},
            "channel": "l2_internal", "route_type": "task.dispatch",
            "action": "asset.query",
            "capability_id": "CAP.DIGITAL_ASSET.ASSET_QUERY",
            "capability_dictionary_version": "test_1", "registry_version": "test_registry_1",
            "idempotency_key": "idem_http_flow_query_001", "deadline_at": "2099-12-31T23:59:59+08:00",
            "actor": {"person_id": "tester_a", "tenant_id": "tenant_demo"},
            "context": {"workflow_instance_id": "flow_http_001", "node_id": "node_http_001", "task_id": "task_http_001", "data_refs": []},
            "payload": {"asset_types": ["skill"]},
        }
        status, first = self.request_json("/api/flow/tasks", method="POST", body=envelope)
        self.assertEqual(status, 201)
        self.assertTrue(first["ok"])
        self.assertEqual(first["data"]["service_code"], "l2.digital_asset.asset.query")
        self.assertEqual(first["data"]["standard_response"]["code"], "FLOW_TASK_SUCCEEDED")
        self.assertEqual(first["data"]["standard_response"]["reply_type"], "success")

        status, replay = self.request_json("/api/flow/tasks", method="POST", body=envelope)
        self.assertEqual(status, 200)
        self.assertTrue(replay["data"]["idempotent_replay"])

    def test_http_l2_kb_requires_l1_instance_and_index_callbacks(self) -> None:
        status, created = self.request_json("/api/assets", method="POST", body={
            "actor": "tester_a", "asset_type": "knowledge_base", "asset_name": "个人工艺知识库",
            "scope": "personal", "description": "验证 L2 资产到 L1 实例映射",
        })
        self.assertEqual(status, 201)
        asset_id = created["data"]["asset_id"]
        status, source_result = self.request_json(f"/api/assets/{asset_id}/sources", method="POST", body={
            "actor": "tester_a", "file_name": "工艺规程.docx",
        })
        self.assertEqual(status, 201)
        source_id = source_result["data"]["source_id"]
        self.request_json(f"/api/sources/{source_id}/parse", method="POST", body={
            "actor": "tester_a", "outcome": "success",
        })
        status, binding_result = self.request_json(
            f"/api/assets/{asset_id}/request-l1-knowledge-base", method="POST", body={"actor": "tester_a"},
        )
        self.assertEqual(status, 201)
        binding_id = binding_result["data"]["binding_id"]
        status, _ = self.request_json(
            f"/api/knowledge-base-instances/{binding_id}/register", method="POST", body={
                "actor": "engine_admin", "outcome": "ready", "l1_kb_id": "l1kb_http",
                "namespace": "test.http", "callback_mode": "mock",
            },
        )
        self.assertEqual(status, 200)
        status, _ = self.request_json(f"/api/sources/{source_id}/register-index", method="POST", body={
            "actor": "engine_admin", "outcome": "indexed", "chunk_count": 5,
            "vector_count": 5, "index_version": "http-v1", "callback_mode": "mock",
        })
        self.assertEqual(status, 200)
        status, state = self.request_json("/api/state?actor=tester_a")
        self.assertEqual(status, 200)
        source = next(item for item in state["data"]["sources"] if item["source_id"] == source_id)
        self.assertEqual(source["vector_status"], "indexed")
        self.assertEqual(source["index_evidence"]["chunk_count"], 5)

    def test_http_direct_id_cannot_bypass_personal_permission(self) -> None:
        status, created = self.request_json(
            "/api/assets", method="POST",
            body={"actor": "tester_a", "asset_type": "skill", "asset_name": "私有技能"},
        )
        self.assertEqual(status, 201)
        asset_id = created["data"]["asset_id"]
        status, denied = self.request_json(f"/api/assets/{asset_id}?actor=tester_b")
        self.assertEqual(status, 403)
        self.assertEqual(denied["code"], "NO_READ_PERMISSION")

    def test_http_l4_request_returns_standard_response(self) -> None:
        server_module.ENGINE = DigitalAssetEngine(Path(self.tmp.name) / "l4_api.db", seed_demo=True)
        status, body = self.request_json(
            "/api/l4/requests", method="POST",
            body={
                "actor": "tester_a",
                "scenario_code": "use_fermentation_skill",
                "source_layer": "L4",
            },
        )
        self.assertEqual(status, 201)
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["standard_response"]["type"], "immediate")
        self.assertTrue(body["data"]["trace_id"].startswith("trace_"))

    def test_http_agent_executes_fixed_tool_and_rejects_bad_input(self) -> None:
        server_module.ENGINE = DigitalAssetEngine(Path(self.tmp.name) / "runtime_api.db", seed_demo=True)
        status, body = self.request_json(
            "/api/agents/asset_demo_fermentation_agent/execute", method="POST",
            body={
                "actor": "tester_a",
                "input": {"temperature_c": 34, "ph": 6.5, "dissolved_oxygen_pct": 12},
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(body["data"]["output"]["conclusion"], "abnormal")
        self.assertEqual(body["data"]["output"]["abnormal_count"], 2)
        self.assertEqual(body["data"]["confirmation_status"], "pending")

        status, denied = self.request_json(
            "/api/agents/asset_demo_fermentation_agent/execute", method="POST",
            body={
                "actor": "tester_a",
                "input": {"temperature_c": "bad", "ph": 6.5, "dissolved_oxygen_pct": 12},
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(denied["code"], "BAD_SKILL_INPUT")

    def test_http_created_skill_must_validate_before_it_can_execute(self) -> None:
        status, created = self.request_json(
            "/api/assets", method="POST",
            body={
                "actor": "tester_a", "asset_type": "skill", "asset_name": "新建可执行技能",
                "description": "通过固定工具绑定形成真实能力", "scope": "personal",
                "config": {
                    "candidate_source": "evolution",
                    "requirement": {"input_definition": "批次参数", "output_definition": "异常项"},
                },
            },
        )
        self.assertEqual(status, 201)
        asset_id = created["data"]["asset_id"]
        status, blocked = self.request_json(
            f"/api/assets/{asset_id}/activate-personal", method="POST", body={"actor": "tester_a"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(blocked["code"], "SKILL_TOOL_NOT_BOUND")
        status, bound = self.request_json(
            f"/api/assets/{asset_id}/bind-skill-implementation", method="POST",
            body={
                "actor": "tester_a",
                "tool_id": "fermentation_anomaly_checker",
                "tool_version": "1.0.0",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(bound["data"]["config"]["lifecycle_stage"], "implementation_bound")
        status, blocked = self.request_json(
            f"/api/assets/{asset_id}/activate-personal", method="POST", body={"actor": "tester_a"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(blocked["code"], "SKILL_NOT_VALIDATED")
        status, validated = self.request_json(
            f"/api/assets/{asset_id}/validate-skill", method="POST", body={"actor": "tester_a"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(validated["data"]["status"], "passed")
        for role in ("primary", "backup"):
            status, _ = self.request_json(
                f"/api/assets/{asset_id}/model-evaluations", method="POST",
                body={
                    "actor": "tester_a", "model_role": role,
                    "model_id": f"model-{role}", "model_version": "1.0.0",
                    "dataset_ref": "dataset://fixed/v1", "metric_name": "accuracy",
                    "metric_value": 0.9, "conclusion": "passed",
                },
            )
            self.assertEqual(status, 201)
        status, _ = self.request_json(
            f"/api/assets/{asset_id}/activate-personal", method="POST", body={"actor": "tester_a"},
        )
        self.assertEqual(status, 200)
        status, executed = self.request_json(
            f"/api/skills/{asset_id}/execute", method="POST",
            body={
                "actor": "tester_a",
                "input": {"temperature_c": 30, "ph": 6.5, "dissolved_oxygen_pct": 35},
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(executed["data"]["output"]["conclusion"], "normal")

    def test_http_skill_development_and_candidate_callback_flow(self) -> None:
        status, created = self.request_json(
            "/api/assets", method="POST",
            body={
                "actor": "tester_a", "asset_type": "skill", "asset_name": "Skill研发接口测试",
                "description": "验证需求提交与候选回传不是同一步", "scope": "personal",
                "config": {
                    "candidate_source": "evolution",
                    "requirement": {
                        "input_definition": "温度、pH、溶氧",
                        "output_definition": "异常项与风险等级",
                        "acceptance_criteria": "固定测试全部通过",
                    },
                },
            },
        )
        self.assertEqual(status, 201)
        asset_id = created["data"]["asset_id"]
        status, submitted = self.request_json(
            f"/api/assets/{asset_id}/submit-development", method="POST",
            body={"actor": "tester_a"},
        )
        self.assertEqual(status, 201)
        development_id = submitted["data"]["development_id"]
        status, candidate = self.request_json(
            f"/api/development-requests/{development_id}/register-candidate", method="POST",
            body={
                "actor": "engine_admin",
                "tool_id": "fermentation_anomaly_checker",
                "tool_version": "1.0.0",
                "callback_mode": "mock",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(candidate["data"]["status"], "ready_to_bind")
        status, bound = self.request_json(
            f"/api/assets/{asset_id}/bind-skill-implementation", method="POST",
            body={
                "actor": "tester_a",
                "tool_id": candidate["data"]["candidate_tool_id"],
                "tool_version": candidate["data"]["candidate_tool_version"],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(bound["data"]["config"]["lifecycle_stage"], "implementation_bound")

    def test_http_material_asset_is_rejected(self) -> None:
        status, rejected = self.request_json(
            "/api/assets", method="POST",
            body={
                "actor": "tester_a", "asset_type": "material", "asset_name": "报告模板",
                "description": "可复用报告模板", "scope": "personal",
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(rejected["code"], "BAD_ASSET_TYPE")

    def test_http_knowledge_source_upload_download_and_permission(self) -> None:
        status, created = self.request_json(
            "/api/assets", method="POST",
            body={
                "actor": "tester_a", "asset_type": "knowledge_base",
                "asset_name": "个人工艺知识库", "description": "知识源容器",
                "scope": "personal",
            },
        )
        self.assertEqual(status, 201)
        asset_id = created["data"]["asset_id"]
        content = b"knowledge-source-original"
        status, uploaded = self.request_json(
            f"/api/console/assets/{asset_id}/knowledge-source-files", method="POST",
            body={
                "actor": "tester_a", "file_name": "process.docx",
                "content_type": "application/octet-stream",
                "data_base64": base64.b64encode(content).decode("ascii"),
                "description": "发酵工艺原始资料",
            },
        )
        self.assertEqual(status, 201)
        source = uploaded["data"]
        self.assertEqual(source["parse_status"], "pending")
        self.assertEqual(source["checksum_sha256"], hashlib.sha256(content).hexdigest())
        source_id = source["source_id"]
        with urllib.request.urlopen(
            f"{self.base}/api/knowledge-sources/{source_id}/download?actor=tester_a", timeout=3,
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), content)
        status, denied = self.request_json(
            f"/api/knowledge-sources/{source_id}/download?actor=tester_b",
        )
        self.assertEqual(status, 403)
        self.assertEqual(denied["code"], "NO_KNOWLEDGE_SOURCE_DOWNLOAD_PERMISSION")

    def test_http_l4_capability_execution_returns_one_trace_and_route(self) -> None:
        server_module.ENGINE = DigitalAssetEngine(Path(self.tmp.name) / "l4_execute_api.db", seed_demo=True)
        status, body = self.request_json(
            "/api/l4/capability-executions", method="POST",
            body={
                "actor": "tester_a", "source_layer": "L4",
                "target_asset_id": "asset_demo_fermentation_agent",
                "service_code": "fermentation_batch_check",
                "request_text": "检查发酵批次参数",
                "input": {"temperature_c": 34, "ph": 6.5, "dissolved_oxygen_pct": 12},
            },
        )
        self.assertEqual(status, 201)
        result = body["data"]
        self.assertEqual(result["output"]["abnormal_count"], 2)
        self.assertEqual(result["trace_id"], result["standard_response"]["trace_id"])
        self.assertTrue(any(step["component"] == "功能登记库" for step in result["l4_route"]))
        self.assertTrue(any(step["component"] == "固定工具适配器" for step in result["l4_route"]))


if __name__ == "__main__":
    unittest.main()
