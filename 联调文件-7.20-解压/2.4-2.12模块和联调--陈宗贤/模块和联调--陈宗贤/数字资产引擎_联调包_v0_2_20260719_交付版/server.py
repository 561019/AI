# -*- coding: utf-8 -*-
"""数字资产引擎 MVP HTTP 服务。

所有业务 API 都显式携带当前真人 actor，并把权限判定交给 engine.py；静态页面
不能通过隐藏按钮替代服务端判权。
"""

from __future__ import annotations

import json
import mimetypes
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

try:
    from .engine import DigitalAssetEngine, EngineError, demo_db_path
except ImportError:  # 兼容直接执行 python server.py
    from engine import DigitalAssetEngine, EngineError, demo_db_path


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
ENGINE = DigitalAssetEngine(demo_db_path())


class Handler(BaseHTTPRequestHandler):
    server_version = "DigitalAssetEngineDemo/0.9"

    def log_message(self, fmt: str, *args) -> None:
        print("[digital-asset-demo]", fmt % args)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _success(self, data=None, message: str = "操作成功", status: int = 200) -> None:
        self._send_json({"ok": True, "data": data, "message": message}, status)

    def _send_file(self, item: dict) -> None:
        path = Path(item["storage_path"])
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", item.get("content_type") or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(item['original_name'])}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, exc: Exception) -> None:
        if isinstance(exc, EngineError):
            self._send_json(
                {"ok": False, "data": None, "code": exc.code, "message": exc.message},
                exc.status,
            )
        else:
            self._send_json(
                {"ok": False, "data": None, "code": "SERVER_ERROR", "message": str(exc)},
                500,
            )

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        if length > 15 * 1024 * 1024:
            raise EngineError("请求体超过 15 MB，拒绝读取", 413, "REQUEST_BODY_TOO_LARGE")
        raw = self.rfile.read(length).decode("utf-8")
        value = json.loads(raw or "{}")
        if not isinstance(value, dict):
            raise EngineError("请求体必须是 JSON 对象", 400, "BAD_JSON_BODY")
        return value

    @staticmethod
    def _query(parsed) -> dict[str, list[str]]:
        return parse_qs(parsed.query)

    def _actor(self, parsed, payload: dict | None = None) -> str:
        payload = payload or {}
        query = self._query(parsed)
        envelope_actor = payload.get("actor")
        # 标准 L2 任务信封中的 actor 是对象，必须保留给 engine.py 复核
        # person_id，不能像控制台兼容接口那样 pop 掉并转成 dict 字符串。
        if isinstance(envelope_actor, dict):
            actor = envelope_actor.get("person_id") or query.get("actor", [None])[0]
        else:
            actor = payload.pop("actor", None) or query.get("actor", [None])[0]
        if not actor:
            raise EngineError("业务 API 必须显式提供当前真人 actor", 401, "ACTOR_REQUIRED")
        return str(actor)

    @staticmethod
    def _console_flow_envelope(actor: str, action: str, service_code: str, payload: dict) -> dict:
        """本地控制台兼容层：把页面操作转换为完整的 L2 流程派发信封。

        此方法不属于跨引擎协议；其他引擎联调只能调用 /api/flow/tasks。
        """
        token = uuid.uuid4().hex
        return {
            "protocol_version": "1.0",
            "message_id": f"msg_console_{token}",
            "trace_id": f"trace_console_{token}",
            "request_id": f"req_console_{token}",
            "parent_message_id": "msg_l4_console",
            "source": {"layer": "L2", "service_code": "l2.workflow_execution"},
            "target": {"layer": "L2", "service_code": "l2.digital_asset"},
            "channel": "l2_internal",
            "route_type": "task.dispatch",
            "action": action,
            "service_code": service_code,
            "capability_id": f"CAP.DIGITAL_ASSET.{action.upper().replace('.', '_')}",
            "capability_dictionary_version": "mock_2026.07.17",
            "registry_version": "mock_registry_2026.07.17",
            "actor": {"person_id": actor, "tenant_id": "tenant_hanhe"},
            "context": {
                "workflow_instance_id": f"wf_console_{token}",
                "node_id": f"node_console_{token}",
                "task_id": f"task_console_{token}",
                "data_refs": [],
            },
            "idempotency_key": f"console_{token}",
            "deadline_at": "2099-12-31T23:59:59+08:00",
            "payload": payload,
        }

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                return self._success(
                    {
                        "database": str(ENGINE.db_path),
                        "version": "0.9",
                        "assetTypes": ["agent", "skill", "knowledge_base"],
                        "execution": "fixed-tool-adapter",
                        "knowledgeSourceStorage": "local-object-adapter",
                        "skillModelEvidence": "primary-and-backup-evaluations",
                        "authorization": "external-foundation-module-mock",
                        "creationEntry": "flow-task-envelope",
                    },
                    "数字资产引擎演示服务运行中",
                )
            if parsed.path == "/api/state":
                actor = self._actor(parsed)
                return self._success(ENGINE.state(actor), "已按当前真人过滤工作台状态")
            match = re.fullmatch(r"/api/assets/([^/]+)", parsed.path)
            if match:
                actor = self._actor(parsed)
                return self._success(
                    ENGINE.get_asset_for_actor(actor, match.group(1)),
                    "资产详情已通过服务端权限判定",
                )
            match = re.fullmatch(r"/api/knowledge-sources/([^/]+)/download", parsed.path)
            if match:
                actor = self._actor(parsed)
                return self._send_file(ENGINE.knowledge_source_for_download(actor, match.group(1)))
            return self._serve_static(parsed.path)
        except Exception as exc:
            return self._send_error(exc)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            actor = self._actor(parsed, payload)

            if parsed.path == "/api/l4/requests":
                return self._success(
                    ENGINE.invoke_l4_scenario(actor, payload),
                    "L4 请求已按层间接口规范处理并留痕",
                    201,
                )

            if parsed.path == "/api/l4/capability-executions":
                return self._success(
                    ENGINE.execute_l4_capability(actor, payload),
                    "L4请求已通过层接口、功能登记、Agent/Skill和固定工具真实执行",
                    201,
                )

            if parsed.path == "/api/reset":
                return self._success(ENGINE.reset_demo(actor), "演示数据已重置")

            if parsed.path == "/api/flow/tasks":
                receipt = ENGINE.process_flow_task(actor, payload)
                # HTTP 层同时保留回执的顶层字段，并提供固定的 standard_response
                # 容器，避免联调方因控制台兼容包装而猜测真正的流程回执位置。
                response = {**receipt, "standard_response": receipt}
                return self._success(
                    response,
                    "流程执行引擎任务已由数字资产引擎处理并返回标准回执",
                    200 if receipt.get("idempotent_replay") else (202 if receipt.get("reply_type") == "accepted" else 201),
                )

            if parsed.path == "/api/assets":
                # 兼容旧客户端，但服务端仍强制包装为流程执行引擎任务，禁止
                # L4/页面直接绕过统一调用链写入数字资产登记册。
                envelope = self._console_flow_envelope(
                    actor, "asset.create", "l2.digital_asset.asset.create", payload
                )
                receipt = ENGINE.process_flow_task(actor, envelope)
                if receipt.get("reply_type") == "failed":
                    raise EngineError(receipt["message"], 400, receipt["code"])
                return self._success(
                    receipt["result"],
                    "兼容入口已转换为流程任务并完成登记",
                    201,
                )

            match = re.fullmatch(r"/api/console/assets/([^/]+)/knowledge-source-files", parsed.path)
            if match:
                return self._success(
                    ENGINE.upload_knowledge_source(actor, match.group(1), payload),
                    "本地控制台已将原件交给 L1.7 对象存储 Mock；正式联调只传 artifact_ref",
                    201,
                )

            if re.fullmatch(r"/api/assets/([^/]+)/knowledge-source-files", parsed.path):
                raise EngineError(
                    "该路径仅供本地控制台兼容使用；跨引擎请先由 L1.7 提供 artifact_ref，再调用 /api/flow/tasks",
                    410,
                    "CONSOLE_ONLY_ENDPOINT_MOVED",
                )

            match = re.fullmatch(r"/api/assets/([^/]+)/request-l1-knowledge-base", parsed.path)
            if match:
                return self._success(
                    ENGINE.request_l1_knowledge_base(actor, match.group(1), payload),
                    "L1 知识库实例申请已登记；尚未收到 L1 回执，不能宣称可检索",
                    201,
                )

            match = re.fullmatch(r"/api/knowledge-base-instances/([^/]+)/register", parsed.path)
            if match:
                return self._success(
                    ENGINE.register_l1_knowledge_base(actor, match.group(1), payload),
                    "L1 知识库实例回执已登记",
                )

            match = re.fullmatch(r"/api/assets/([^/]+)/validate-skill", parsed.path)
            if match:
                return self._success(
                    ENGINE.validate_skill(actor, match.group(1), payload),
                    "技能已通过固定工具测试，可以进入启用或发布流程",
                )

            match = re.fullmatch(r"/api/assets/([^/]+)/model-evaluations", parsed.path)
            if match:
                return self._success(
                    ENGINE.register_skill_model_evaluation(actor, match.group(1), payload),
                    "技能模型评测证据已登记；主力和备用模型都通过后方可启用或发布",
                    201,
                )

            match = re.fullmatch(r"/api/assets/([^/]+)/bind-skill-implementation", parsed.path)
            if match:
                return self._success(
                    ENGINE.bind_skill_implementation(actor, match.group(1), payload),
                    "Skill 实现已绑定；仍须通过固定测试后才能启用或发布",
                )

            match = re.fullmatch(r"/api/assets/([^/]+)/submit-development", parsed.path)
            if match:
                return self._success(
                    ENGINE.submit_skill_development(actor, match.group(1), payload),
                    "Skill 研发需求已登记并提交到目标研发队列；当前尚未获得可执行实现",
                    201,
                )

            match = re.fullmatch(r"/api/development-requests/([^/]+)/register-candidate", parsed.path)
            if match:
                return self._success(
                    ENGINE.register_skill_candidate(actor, match.group(1), payload),
                    "候选实现已回传并登记；仍须由需求创建人绑定并运行固定测试",
                )

            match = re.fullmatch(r"/api/skills/([^/]+)/execute", parsed.path)
            if match:
                return self._success(
                    ENGINE.execute_skill(actor, match.group(1), payload),
                    "技能已由固定版本工具真实执行并留痕",
                    201,
                )

            match = re.fullmatch(r"/api/agents/([^/]+)/execute", parsed.path)
            if match:
                return self._success(
                    ENGINE.execute_agent(actor, match.group(1), payload),
                    "Agent 已编排已发布技能并返回真实执行结果",
                    201,
                )

            match = re.fullmatch(r"/api/executions/([^/]+)/confirm", parsed.path)
            if match:
                return self._success(
                    ENGINE.confirm_execution(actor, match.group(1), payload),
                    "执行结果已由本次操作真人确认并留痕",
                )

            asset_routes = {
                "update": (ENGINE.update_asset, "草稿已修改并生成新版本"),
                "activate-personal": (ENGINE.activate_personal, "资产已个人启用；这不是发布"),
                "submit-adoption": (ENGINE.submit_adoption, "部门采纳申请已提交给固定审批岗位真人"),
                "submit-publish": (ENGINE.submit_publish, "发布申请已提交，尚未发布"),
                "disable": (ENGINE.disable_asset, "资产已停用，后续变更全部锁定"),
                "delete-draft": (ENGINE.delete_draft, "个人草稿已逻辑删除，版本与留痕保留"),
                "sync": (ENGINE.sync_registry, "功能登记状态已同步"),
            }
            for suffix, (method, message) in asset_routes.items():
                match = re.fullmatch(rf"/api/assets/([^/]+)/{re.escape(suffix)}", parsed.path)
                if match:
                    return self._success(method(actor, match.group(1), payload), message)

            # 旧 /publish 只作为兼容入口提交审批，绝不直接变成已发布。
            match = re.fullmatch(r"/api/assets/([^/]+)/publish", parsed.path)
            if match:
                return self._success(
                    ENGINE.submit_publish(actor, match.group(1), payload),
                    "兼容入口已转换为发布申请，尚未发布",
                )

            match = re.fullmatch(r"/api/assets/([^/]+)/sources", parsed.path)
            if match:
                return self._success(
                    ENGINE.add_source(actor, match.group(1), payload),
                    "知识源已登记；解析由文档表格解析引擎承担",
                    201,
                )

            # 旧 material 入口只登记知识源，不再暗示数字资产引擎存储/解析原文。
            match = re.fullmatch(r"/api/assets/([^/]+)/material", parsed.path)
            if match:
                mapped = dict(payload)
                mapped.setdefault("file_name", mapped.pop("title", None))
                return self._success(
                    ENGINE.add_source(actor, match.group(1), mapped),
                    "素材已作为知识源登记，尚未解析",
                    201,
                )

            match = re.fullmatch(r"/api/workflows/([^/]+)/(approve|reject)", parsed.path)
            if match:
                workflow_id, operation = match.groups()
                if operation == "approve":
                    return self._success(
                        ENGINE.approve_workflow(actor, workflow_id, payload),
                        "审批已由固定岗位当前真人完成",
                    )
                return self._success(
                    ENGINE.reject_workflow(actor, workflow_id, payload),
                    "工作流已驳回并保留原因",
                )

            match = re.fullmatch(r"/api/sources/([^/]+)/parse", parsed.path)
            if match:
                return self._success(
                    ENGINE.parse_source(actor, match.group(1), payload),
                    "已登记外部解析引擎返回状态",
                )

            match = re.fullmatch(r"/api/sources/([^/]+)/register-index", parsed.path)
            if match:
                return self._success(
                    ENGINE.register_source_index(actor, match.group(1), payload),
                    "L1 切片与向量索引回执已登记",
                )

            return self._send_json(
                {"ok": False, "data": None, "code": "API_NOT_FOUND", "message": "接口不存在"},
                404,
            )
        except Exception as exc:
            return self._send_error(exc)

    def _serve_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        safe = path.lstrip("/").replace("\\", "/")
        target = (WEB / safe).resolve()
        if not str(target).startswith(str(WEB.resolve())) or not target.exists() or not target.is_file():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix in {".html", ".css", ".js"}:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"数字资产引擎 MVP 已启动：http://127.0.0.1:{port}")
    print("按 Ctrl+C 停止。")
    server.serve_forever()


if __name__ == "__main__":
    main()
