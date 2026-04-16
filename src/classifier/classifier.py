"""요청 분류기 — 5분류 지원.

분류: code_fix, feature, research, review, unsupported
"""
from __future__ import annotations

TASK_TYPES = ("code_fix", "feature", "research", "review", "unsupported")

_KEYWORD_MAP: dict[str, list[str]] = {
    "code_fix": ["수정", "버그", "에러", "오류", "fix", "bug", "patch", "hotfix", "디버그", "debug"],
    "feature":  ["기능", "추가", "구현", "개발", "feature", "implement", "build", "만들어"],
    "research": ["조사", "리서치", "분석", "비교", "research", "analyze", "compare", "탐색"],
    "review":   ["리뷰", "검토", "감사", "review", "audit", "inspect", "점검"],
}


def classify_request(raw_input: str) -> str:
    """raw_input을 분석하여 task_type 문자열을 반환한다."""
    text = (raw_input or "").strip().lower()
    if not text:
        return "unsupported"

    # 우선순위: code_fix > feature > research > review
    for task_type in ("code_fix", "feature", "research", "review"):
        if any(kw in text for kw in _KEYWORD_MAP[task_type]):
            return task_type

    return "unsupported"
