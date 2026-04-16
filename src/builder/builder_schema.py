from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BuilderInput:
    raw_input: str
    task_type: str
    plan: list[dict]


@dataclass
class BuilderStep:
    step:   int
    action: str

    def __post_init__(self) -> None:
        if self.step < 1:
            raise ValueError(f"step must be >= 1, got {self.step}")
        if not self.action.strip():
            raise ValueError("action must not be empty")

    def to_dict(self) -> dict:
        return {"step": self.step, "action": self.action}


BUILDER_STATUS_CREATED = "created"
BUILDER_STATUS_FAILED  = "failed"


@dataclass
class BuilderOutput:
    builder_output:  list[BuilderStep]
    builder_status:  str

    def __post_init__(self) -> None:
        if self.builder_status not in (BUILDER_STATUS_CREATED, BUILDER_STATUS_FAILED):
            raise ValueError(f"builder_status must be 'created' or 'failed', got {self.builder_status!r}")
        if self.builder_status == BUILDER_STATUS_CREATED and not self.builder_output:
            raise ValueError("builder_output must not be empty when builder_status is 'created'")

    def to_state_dict(self) -> dict:
        return {
            "builder_output":  [s.to_dict() for s in self.builder_output],
            "builder_status":  self.builder_status,
        }
