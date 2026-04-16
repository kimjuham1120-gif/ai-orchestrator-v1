"""1차 규칙 기반 리뷰 — 체크리스트 키워드 검사."""
from __future__ import annotations

from src.reviewer.reviewer_schema import (
    CheckResult, ReviewerResult,
    CHECK_PASSED, SCOPE_DRIFT, OVER_MODIFY, TEST_MISSING,
)
from src.reviewer.reviewer_checklist import (
    SCOPE_DRIFT_KEYWORDS, OVER_MODIFY_KEYWORDS, TEST_KEYWORDS,
    SUMMARY_SCOPE_OK, SUMMARY_OVER_OK, SUMMARY_TEST_OK,
    SUMMARY_SCOPE_WARN, SUMMARY_OVER_WARN, SUMMARY_TEST_WARN,
)


def _actions_text(builder_output: list) -> str:
    parts: list[str] = []
    for item in builder_output:
        if isinstance(item, dict):
            parts.append(item.get("action", ""))
        elif isinstance(item, str):
            parts.append(item)
    return " ".join(parts).lower()


def _check_scope_drift(text: str) -> CheckResult:
    hit = any(kw in text for kw in SCOPE_DRIFT_KEYWORDS)
    return CheckResult(
        key=SCOPE_DRIFT,
        status=SCOPE_DRIFT if hit else CHECK_PASSED,
        summary=SUMMARY_SCOPE_WARN if hit else SUMMARY_SCOPE_OK,
    )


def _check_over_modify(text: str) -> CheckResult:
    hit = any(kw in text for kw in OVER_MODIFY_KEYWORDS)
    return CheckResult(
        key=OVER_MODIFY,
        status=OVER_MODIFY if hit else CHECK_PASSED,
        summary=SUMMARY_OVER_WARN if hit else SUMMARY_OVER_OK,
    )


def _check_test_missing(text: str) -> CheckResult:
    mentioned = any(kw in text for kw in TEST_KEYWORDS)
    return CheckResult(
        key=TEST_MISSING,
        status=CHECK_PASSED if mentioned else TEST_MISSING,
        summary=SUMMARY_TEST_OK if mentioned else SUMMARY_TEST_WARN,
    )


def run_rule_check(plan: list, builder_output: list) -> ReviewerResult:
    """1차 규칙 기반 검사 실행."""
    text = _actions_text(builder_output)
    return ReviewerResult(checks=[
        _check_scope_drift(text),
        _check_over_modify(text),
        _check_test_missing(text),
    ])
