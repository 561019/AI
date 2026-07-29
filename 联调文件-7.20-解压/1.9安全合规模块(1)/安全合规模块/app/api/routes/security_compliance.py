"""安全合规模块 API 路由 —— 简化版（仅 check 相关端点）。"""
from typing import Optional
from fastapi import APIRouter, Query
from app.schemas.security import (
    SecurityCheckRequest, SecurityCheckResponse,
    ViolationResult, MaskingResult, DataDomainResult, PermissionResultV2, ModelCheckResult,
)
from app.services.security_gateway import SecurityGateway

router = APIRouter(prefix="/api/l1/security-compliance", tags=["1.9 安全合规"])
gateway = SecurityGateway()


@router.post("/check")
def security_check(req: SecurityCheckRequest):
    """简化的安全检查接口：六层检查 + 最终决策 + hash 链审计。"""
    result = gateway.check(
        input_text=req.input_text,
        real_person_id=req.real_person_id,
        is_emergency=req.is_emergency,
        data_classification=req.data_classification,
        network=req.network,
        model_type=req.model_type,
        output_files=req.output_files,
        output_text=req.output_text,
    )
    return SecurityCheckResponse(
        request_id=result["request_id"],
        audit_id=result["audit_id"],
        trace_id=result.get("trace_id", ""),
        model_check=ModelCheckResult(**result.get("model_check", {})),
        network_check=ViolationResult(**result.get("network_check", {})),
        violation=ViolationResult(**result["violation"]),
        masking=MaskingResult(**result["masking"]),
        data_domain=DataDomainResult(**result.get("data_domain", {})),
        permission=PermissionResultV2(**result["permission"]),
        decision=result["decision"],
        decision_reason=result["decision_reason"],
    )


@router.get("/check/audit-logs")
def check_audit_logs(
    real_person_id: Optional[str] = Query(default=None),
    decision: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
):
    """查询 /check 接口的审计日志（hash 链防篡改）。"""
    filters = {"scene_code": "check", "real_person_id": real_person_id, "decision": decision}
    filters = {k: v for k, v in filters.items() if v is not None}
    result = gateway.audit_repo.search_audit_logs(filters, limit=limit, offset=offset)
    # 附带 AI 返回文件信息
    trace_ids = [item["trace_id"] for item in result["items"] if item.get("trace_id")]
    if trace_ids:
        files_map = gateway.audit_repo.get_output_files_for_traces(trace_ids)
        for item in result["items"]:
            item["output_files"] = files_map.get(item.get("trace_id", ""), [])
    return result


@router.get("/check/audit-integrity")
def check_audit_integrity(limit: int = Query(default=500, le=5000)):
    """校验 /check 审计日志的 hash 链是否被篡改。"""
    return gateway.audit_repo.verify_audit_integrity(limit=limit)


@router.get("/check/trace/{trace_id}")
def check_trace_detail(trace_id: str):
    """查询某次 /check 调用的完整操作留痕。"""
    return gateway.audit_center.get_trace_detail(trace_id)
