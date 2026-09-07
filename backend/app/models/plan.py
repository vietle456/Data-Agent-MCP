from typing import Literal
from pydantic import BaseModel


class PlanStep(BaseModel):
    type: Literal["SQL_QUERY", "PYTHON", "ANSWER"]
    description: str


class Plan(BaseModel):
    intent: Literal["Direct answer", "Code execution"]
    steps: list[PlanStep]
