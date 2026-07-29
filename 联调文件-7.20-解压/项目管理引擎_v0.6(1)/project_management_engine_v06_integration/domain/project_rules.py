from __future__ import annotations

from core.errors import BusinessError
from domain.project_models import ProjectRegistrationCommand


def validate_registration(command: ProjectRegistrationCommand) -> None:
    if not command.project_name.strip():
        raise BusinessError("PROJECT_NAME_REQUIRED", "项目名称不能为空")
    if len(command.project_name.strip()) > 200:
        raise BusinessError("PROJECT_NAME_TOO_LONG", "项目名称不能超过 200 个字符")
    if not command.project_category.strip():
        raise BusinessError("PROJECT_CATEGORY_REQUIRED", "项目类别不能为空")
    if not command.budget_attribute.strip():
        raise BusinessError("BUDGET_ATTRIBUTE_REQUIRED", "预算属性不能为空")
    if not command.initiator_person_id.strip():
        raise BusinessError("INITIATOR_REQUIRED", "立项发起人不能为空")
