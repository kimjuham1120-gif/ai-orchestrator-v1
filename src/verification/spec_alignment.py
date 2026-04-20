"""Spec Alignment — deliverable_spec 대비 실행 결과 검증."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AlignmentResult:
    aligned: bool
    failure_type: Optional[str] = None   # "slice_issue" | "doc_issue" | None
    mismatches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "aligned": self.aligned,
            "failure_type": self.failure_type,
            "mismatches": self.mismatches,
        }


def check_spec_alignment(
    execution_result: dict,
    deliverable_spec: Optional[dict] = None,
    canonical_doc: Optional[dict] = None,
) -> AlignmentResult:
    changed = execution_result.get("changed_files", [])
    test_res = execution_result.get("test_results", "")
    run_log = execution_result.get("run_log", "")

    # spec의 target_files와 비교 — changed_files가 있으면 우선 수행 → 범위 이탈이면 doc_issue
    if changed and deliverable_spec:
        target_files = deliverable_spec.get("target_files", [])
        if target_files:
            out_of_scope = [f for f in changed if f not in target_files]
            if out_of_scope:
                return AlignmentResult(
                    aligned=False,
                    failure_type="doc_issue",
                    mismatches=[f"범위 이탈: {out_of_scope}"],
                )

    # 기본 필드 누락 → slice_issue
    if not changed or not test_res or not run_log:
        return AlignmentResult(
            aligned=False,
            failure_type="slice_issue",
            mismatches=["필수 필드 누락"],
        )

    return AlignmentResult(aligned=True)
