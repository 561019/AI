from typing import Literal

from pydantic import BaseModel


class NeedConfirmationResult(BaseModel):
    level: Literal[3] = 3
    matched: Literal[False] = False
    need_confirmation: Literal[True] = True
    reason: str
    raw_response: str | None = None
