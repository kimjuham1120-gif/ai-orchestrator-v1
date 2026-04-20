"""Builder 스키마."""
from __future__ import annotations
from dataclasses import dataclass, field

BUILDER_STATUS_CREATED = "builder_created"


@dataclass
class BuilderResult:
    builder_output: list[dict] = field(default_factory=list)
    builder_status: str = BUILDER_STATUS_CREATED

    def to_state_dict(self) -> dict:
        return {
            "builder_output": self.builder_output,
            "builder_status": self.builder_status,
        }
