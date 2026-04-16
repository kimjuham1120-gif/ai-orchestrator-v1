from __future__ import annotations

from dataclasses import dataclass, field

SCOPE_DRIFT  = "scope_drift"
OVER_MODIFY  = "over_modify"
TEST_MISSING = "test_missing"
CHECK_PASSED = "passed"

VALID_STATUSES = frozenset({SCOPE_DRIFT, OVER_MODIFY, TEST_MISSING, CHECK_PASSED})


@dataclass
class CheckResult:
    key:     str
    status:  str
    summary: str

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {self.status!r}")
        if not self.summary.strip():
            raise ValueError("summary must not be empty")

    def to_dict(self) -> dict:
        return {"key": self.key, "status": self.status, "summary": self.summary}


@dataclass
class ReviewerResult:
    checks: list[CheckResult] = field(default_factory=list)

    def to_feedback(self) -> list[str]:
        return [c.summary for c in self.checks]

    def to_dict(self) -> dict:
        return {"checks": [c.to_dict() for c in self.checks]}

    def has_warnings(self) -> bool:
        return any(c.status != CHECK_PASSED for c in self.checks)
