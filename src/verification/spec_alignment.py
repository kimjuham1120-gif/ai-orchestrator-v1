"""Spec Alignment Checker — 실행 결과가 frozen doc 명세에 부합하는지 검증.

실패 시 두 가지 복귀 경로:
  - slice 문제 → task slice queue로 복귀
  - doc 문제 → cross-audit / canonical doc 재개정 경로로 복귀
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AlignmentResult:
    """정합성 검증 결과."""
    aligned:       bool = True
    failure_type:  str = ""     # "" | "slice_issue" | "doc_issue"
    issues:        list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "aligned": self.aligned,
            "failure_type": self.failure_type,
            "issues": self.issues,
        }


def check_spec_alignment(
    execution_result: dict,
    deliverable_spec: dict | None = None,
    canonical_doc: dict | None = None,
) -> AlignmentResult:
    """
    실행 결과가 deliverable_spec / canonical_doc에 부합하는지 검증.
    v1 baseline: 기본 필드 존재 여부 + 간단한 scope 체크.
    TODO: LLM 기반 정합성 분석
    """
    issues = []

    if not execution_result:
        return AlignmentResult(aligned=False, failure_type="slice_issue", issues=["execution_result 없음"])

    # 1. 기본 필드 체크
    changed_files = execution_result.get("changed_files", [])
    if not changed_files:
        issues.append("변경된 파일 없음")

    # 2. spec 범위 체크 (spec이 있을 때만)
    if deliverable_spec:
        spec_goal = deliverable_spec.get("goal", "")
        constraints = deliverable_spec.get("constraints", [])
        # 간단한 scope drift 체크: forbidden action에 해당하는 파일 변경 감지
        # v1 baseline은 경고만
        for constraint in constraints:
            if "scope" in constraint.lower():
                # target_files가 지정되어 있으면 범위 이탈 체크
                target = deliverable_spec.get("target_files", [])
                if target:
                    for f in changed_files:
                        if not any(t in f for t in target):
                            issues.append(f"scope 이탈 의심: {f}")

    if not issues:
        return AlignmentResult(aligned=True)

    # 실패 유형 판단
    scope_issues = [i for i in issues if "scope" in i.lower()]
    if scope_issues:
        return AlignmentResult(aligned=False, failure_type="doc_issue", issues=issues)

    return AlignmentResult(aligned=False, failure_type="slice_issue", issues=issues)
