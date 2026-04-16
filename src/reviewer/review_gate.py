"""3-Layer Review Gate — 규칙 + LLM + 승인 통합.

1차: rule_checker (키워드 기반)
2차: llm_reviewer (LLM 기반, v1은 stub)
3차: 승인 게이트 (1차+2차 통과 시 approval로 전이)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from src.reviewer.rule_checker import run_rule_check
from src.reviewer.llm_reviewer import run_llm_review, LLMReviewResult
from src.reviewer.reviewer_schema import ReviewerResult


@dataclass
class ReviewGateResult:
    """3층 리뷰 통합 결과."""
    rule_result:     ReviewerResult | None = None
    llm_result:      LLMReviewResult | None = None
    gate_passed:     bool = False
    block_reason:    str = ""
    feedback:        list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rule_result": self.rule_result.to_dict() if self.rule_result else None,
            "llm_result": self.llm_result.to_dict() if self.llm_result else None,
            "gate_passed": self.gate_passed,
            "block_reason": self.block_reason,
            "feedback": self.feedback,
        }


def run_review_gate(
    plan: list,
    builder_output: list,
    deliverable_spec: dict | None = None,
) -> ReviewGateResult:
    """3층 리뷰를 순서대로 실행하고 통합 결과 반환."""

    # 1차: 규칙 기반
    rule_result = run_rule_check(plan, builder_output)
    feedback = rule_result.to_feedback()

    # 2차: LLM 리뷰
    llm_result = run_llm_review(plan, builder_output, deliverable_spec)

    # 3차: 게이트 판단
    rule_ok = not rule_result.has_warnings()
    llm_ok = llm_result.passed

    if rule_ok and llm_ok:
        return ReviewGateResult(
            rule_result=rule_result,
            llm_result=llm_result,
            gate_passed=True,
            feedback=feedback,
        )

    reasons = []
    if not rule_ok:
        reasons.append("규칙 기반 검사 경고 발생")
    if not llm_ok:
        reasons.append("LLM 리뷰 이슈 발생")

    return ReviewGateResult(
        rule_result=rule_result,
        llm_result=llm_result,
        gate_passed=False,
        block_reason=" / ".join(reasons),
        feedback=feedback,
    )
