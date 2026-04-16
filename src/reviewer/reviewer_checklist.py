"""체크리스트 상수 — LLM prompt 없음, 규칙 문자열만."""
from __future__ import annotations

SCOPE_DRIFT_KEYWORDS: list[str] = [
    "새로운 기능", "기능 추가", "신규 요구", "범위 확대",
    "new feature", "add feature", "additional feature", "extend scope", "out of scope",
]

OVER_MODIFY_KEYWORDS: list[str] = [
    "whole project", "large refactor", "many files", "broad changes",
    "전체 파일", "대규모 리팩토링", "전면 수정",
]

TEST_KEYWORDS: list[str] = [
    "test", "pytest", "테스트", "verify", "검증",
]

SUMMARY_SCOPE_OK   = "범위 이탈 없음"
SUMMARY_OVER_OK    = "과잉 수정 없음"
SUMMARY_TEST_OK    = "테스트 포인트 확인 필요"

SUMMARY_SCOPE_WARN = "범위 이탈 가능성 있음 — 재확인 필요"
SUMMARY_OVER_WARN  = "과잉 수정 위험 — 범위 축소 검토 필요"
SUMMARY_TEST_WARN  = "테스트 언급 없음 — 테스트 포인트 추가 필요"
