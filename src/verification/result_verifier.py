"""Result Verifier — 실행 결과의 완전성 검증.

테스트 결과, changed_files, run_log가 유효한지 확인한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VerificationResult:
    """검증 결과."""
    passed:   bool = True
    issues:   list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "issues": self.issues}


def verify_execution_result(execution_result: dict | None) -> VerificationResult:
    """execution_result dict의 완전성을 검증한다."""
    if not execution_result:
        return VerificationResult(passed=False, issues=["execution_result가 없음"])

    issues = []

    changed_files = execution_result.get("changed_files", [])
    if not changed_files:
        issues.append("changed_files가 비어있음")

    test_results = execution_result.get("test_results", "")
    if not test_results:
        issues.append("test_results가 비어있음")

    run_log = execution_result.get("run_log", "")
    if not run_log:
        issues.append("run_log가 비어있음")

    # 테스트 실패 감지
    test_lower = test_results.lower()
    if "fail" in test_lower or "error" in test_lower:
        issues.append("테스트에 실패 또는 에러가 포함됨")

    return VerificationResult(
        passed=len(issues) == 0,
        issues=issues,
    )
