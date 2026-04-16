"""2차 LLM 리뷰 — v1 baseline은 stub, 실제 LLM 호출은 TODO."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LLMReviewResult:
    """LLM 리뷰 결과."""
    issues:    list[dict] = field(default_factory=list)  # [{severity, message}]
    passed:    bool = True
    model_used: str = ""

    def to_dict(self) -> dict:
        return {
            "issues": self.issues,
            "passed": self.passed,
            "model_used": self.model_used,
        }


def run_llm_review(
    plan: list,
    builder_output: list,
    deliverable_spec: dict | None = None,
) -> LLMReviewResult:
    """
    2차 LLM 기반 리뷰.
    v1 baseline: 항상 통과 반환.
    TODO: OpenRouter 호출로 실제 리뷰
    """
    return LLMReviewResult(
        issues=[],
        passed=True,
        model_used="stub",
    )
