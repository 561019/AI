from __future__ import annotations

import json
from pathlib import Path
from core.errors import BusinessError


class SourceAdmission:
    def __init__(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "source_route_matrix.json"
        self.config = json.loads(path.read_text(encoding="utf-8"))
        self.rules = self.config["rules"]

    def validate(self, message) -> None:
        if message.target.layer != self.config["target_layer"]:
            raise BusinessError("INVALID_TARGET_LAYER", "目标层必须是 L2", http_status=400)
        if message.target.service_code != self.config["target_service_code"]:
            raise BusinessError("INVALID_TARGET_SERVICE", "目标服务必须是 l2.project_management", http_status=400)
        if message.channel != self.config["channel"]:
            raise BusinessError("INVALID_MESSAGE_CHANNEL", "项目管理引擎只接受 l2_internal 通道", http_status=400)

        matched = None
        for rule in self.rules:
            if (
                rule["source_layer"] == message.source.layer
                and rule["source_service_code"] == message.source.service_code
                and message.route_type in rule["route_types"]
            ):
                matched = rule
                break
        if matched is None:
            raise BusinessError(
                "SOURCE_ROUTE_NOT_ALLOWED",
                "来源、层级与 route_type 的组合未获准调用项目管理引擎",
                http_status=403,
            )
        actions = matched["actions"]
        if "*" not in actions and message.action not in actions:
            raise BusinessError(
                "SOURCE_ACTION_NOT_ALLOWED",
                "当前来源不能使用该 route_type 办理此能力",
                http_status=403,
            )
        if message.route_type in {"task.dispatch", "flow.callback"} and message.source.service_code != "l2.workflow_execution":
            raise BusinessError(
                "WORKFLOW_ONLY_ROUTE",
                "只有流程执行引擎可以使用 task.dispatch 或 flow.callback",
                http_status=403,
            )
