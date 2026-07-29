"""审计留痕中心 —— 简化版，仅用于 check 流程的 trace 查询。"""
from typing import Dict
from app.repositories.audit_repository import AuditRepository


class AuditTraceCenter:
    def __init__(self, repo: AuditRepository) -> None:
        self.repo = repo

    def get_trace_detail(self, trace_id: str) -> Dict:
        return {
            "trace_id": trace_id,
            "audit_logs": self.repo.list_audit_logs(trace_id=trace_id, limit=200),
            "trace_spans": self.repo.list_trace_spans(trace_id),
            "observations": self.repo.list_observations(trace_id),
        }
