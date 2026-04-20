"""Result Verifier — 실행 결과 기본 검증."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VerificationResult:
    passed: bool
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "issues": self.issues}


def verify_execution_result(exec_result: Optional[dict]) -> VerificationResult:
    issues = []

    if not exec_result:
        return VerificationResult(passed=False, issues=["실행 결과 없음"])

    changed = exec_result.get("changed_files", [])
    test_res = exec_result.get("test_results", "")
    run_log = exec_result.get("run_log", "")

    if not changed:
        issues.append("changed_files 비어있음")
    if not test_res:
        issues.append("test_results 비어있음")
    if not run_log:
        issues.append("run_log 비어있음")
    if test_res and re.search(r"\bfailed\b", test_res, re.IGNORECASE):
        issues.append("테스트 실패 감지")

    return VerificationResult(passed=len(issues) == 0, issues=issues)
