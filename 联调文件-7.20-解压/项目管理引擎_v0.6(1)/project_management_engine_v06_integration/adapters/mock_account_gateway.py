from __future__ import annotations

from core.errors import BusinessError


class MockAccountGateway:
    """
    模拟 L1.8 账号网关，只提供人员、岗位和组织事实，不作权限结论。
    """

    DEFAULT_NAMES = {
        "PERSON_101": "张三",
        "PERSON_102": "李四",
        "PERSON_103": "王五",
        "PERSON_104": "赵六",
        "DENY_AUTH_001": "授权拒绝测试人员",
        "DENY_REVOKE_001": "收权拒绝测试人员",
    }

    def resolve_person(self, person_id, requested_position_code=None):
        # type: (str, str) -> dict
        normalized = str(person_id).strip()

        if not normalized:
            raise BusinessError(
                "PERSON_ID_REQUIRED",
                "成员人员编号不能为空",
                http_status=400,
            )

        if normalized.startswith("UNKNOWN_"):
            raise BusinessError(
                "PERSON_NOT_FOUND",
                "账号网关未找到该人员",
                http_status=404,
            )

        active = not normalized.startswith("INACTIVE_")
        position_code = requested_position_code or "POSITION_PROJECT_MEMBER"

        return {
            "person_id": normalized,
            "display_name": self.DEFAULT_NAMES.get(
                normalized,
                "Mock用户-" + normalized,
            ),
            "active": active,
            "tenant_id": "tenant_hanhe",
            "organization_code": "ORG_HANHE",
            "position_code": position_code,
            "mock": True,
        }
