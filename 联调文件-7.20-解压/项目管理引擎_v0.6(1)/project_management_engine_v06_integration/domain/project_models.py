from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ProjectGrade(str, Enum):
    SIMPLE = "SIMPLE"
    MAJOR = "MAJOR"


class ProjectStatus(str, Enum):
    INITIATION_PENDING = "INITIATION_PENDING"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    ARCHIVED = "ARCHIVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ProjectRegistrationCommand:
    project_name: str
    project_category: str
    project_grade: ProjectGrade
    budget_attribute: str
    initiator_person_id: str
    description: Optional[str] = None
