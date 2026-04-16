from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlannerInput:
    raw_input: str
    task_type: str


@dataclass
class PlanStep:
    step:        int
    description: str

    def __post_init__(self) -> None:
        if self.step < 1:
            raise ValueError(f"step must be >= 1, got {self.step}")
        if not self.description.strip():
            raise ValueError("description must not be empty")

    def to_dict(self) -> dict:
        return {"step": self.step, "description": self.description}


PLAN_STATUS_CREATED = "created"
PLAN_STATUS_FAILED  = "failed"


@dataclass
class PlannerOutput:
    plan:        list[PlanStep]
    plan_status: str

    def __post_init__(self) -> None:
        if self.plan_status not in (PLAN_STATUS_CREATED, PLAN_STATUS_FAILED):
            raise ValueError(f"plan_status must be 'created' or 'failed', got {self.plan_status!r}")
        if self.plan_status == PLAN_STATUS_CREATED and not self.plan:
            raise ValueError("plan must not be empty when plan_status is 'created'")

    def to_state_dict(self) -> dict:
        return {
            "plan":        [s.to_dict() for s in self.plan],
            "plan_status": self.plan_status,
        }
