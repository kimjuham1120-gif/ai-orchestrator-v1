"""Planner 스키마."""
from __future__ import annotations
from dataclasses import dataclass, field

PLAN_STATUS_CREATED = "plan_created"


@dataclass
class PlanResult:
    plan: list[dict] = field(default_factory=list)
    plan_status: str = PLAN_STATUS_CREATED

    def to_state_dict(self) -> dict:
        return {"plan": self.plan, "plan_status": self.plan_status}
