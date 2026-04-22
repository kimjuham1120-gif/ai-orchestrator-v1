"""
Phase 5 · 사용자 검수 루프 (Day 119~)

역할: Phase 4를 통과한 문서를 사용자에게 보여주고, 피드백 →
      재작성 → 새 버전 축적 사이클을 돌림.

워크플로우:
  현재 버전 (v1)
    ↓ apply_feedback()   — 피드백 적용해 v2 생성
  현재 버전 (v2)
    ↓ apply_feedback()   — 피드백 적용해 v3 생성
  ...
    ↓ confirm_final()    — 사용자 확정 → Phase 6 진입

공개 API:
  apply_feedback(current_doc, user_feedback, raw_input, base_info_doc=None)
    → FeedbackResult
  append_version(existing_versions, new_doc, feedback_applied)
    → list[dict]
  confirm_final(final_doc)
    → ConfirmResult

정책 (scope.md v4 결정사항 #4):
  - 저장 무제한 (DB에 전부)
  - UI는 최근 10개만 표시 (Step 11에서 UI 구현)

환경변수:
  OPENROUTER_API_KEY
  FEEDBACK_MODEL           — 기본: openai/gpt-5.4
  FEEDBACK_TIMEOUT         — 기본: 90.0 초
"""
from __future__ import annotations

from src.utils.llm_utils import call_llm, clean_markdown_wrapper

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.store.artifact_store import utc_now_iso


# ---------------------------------------------------------------------------
# 모델 / 타임아웃 설정
# ---------------------------------------------------------------------------

FEEDBACK_MODEL = os.environ.get("FEEDBACK_MODEL", "openai/gpt-5.4")

try:
    FEEDBACK_TIMEOUT = float(os.environ.get("FEEDBACK_TIMEOUT", "90.0"))
except (ValueError, TypeError):
    FEEDBACK_TIMEOUT = 90.0


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


@dataclass
class FeedbackResult:
    """피드백 적용 결과."""
    status: str                                  # success / failed
    new_doc: Optional[Dict[str, Any]] = None     # 새 버전 문서 ({"document": str, "created_at": str})
    error: Optional[str] = None
    feedback_applied: Optional[str] = None       # 어떤 피드백을 적용했는지 (기록용)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "new_doc": self.new_doc,
            "error": self.error,
            "feedback_applied": self.feedback_applied,
        }

    @property
    def is_success(self) -> bool:
        return self.status == STATUS_SUCCESS and self.new_doc is not None


@dataclass
class ConfirmResult:
    """최종 확정 결과."""
    confirmed: bool
    final_doc: Optional[Dict[str, Any]] = None
    confirmed_at: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "confirmed": self.confirmed,
            "final_doc": self.final_doc,
            "confirmed_at": self.confirmed_at,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# LLM 프롬프트 — 피드백 적용
# ---------------------------------------------------------------------------

_PROMPT_APPLY_FEEDBACK = """\
당신은 사용자 피드백을 받아 문서를 개선하는 전문 편집자입니다.

## 원본 요청
{raw_input}

## 현재 문서 (개선 대상)
{current_document}

## 사용자 피드백
{user_feedback}

{base_info_section}

## 개선 원칙
1. **피드백을 충실히 반영**: 사용자가 지적한 부분을 실제로 개선합니다.
2. **기존 강점 유지**: 피드백에 언급되지 않은 부분은 유지합니다 (통째로 다시 쓰지 않음).
3. **자연스러운 통합**: 개선된 내용이 문서 전체와 어울리도록 합니다.
4. **전체 문서 반환**: 변경 부분만이 아닌, 완성된 전체 문서를 반환합니다.
5. **한국어**: 한국어로 작성.

## 출력 형식
개선된 전체 문서 본문만 마크다운으로 출력하세요.
설명이나 코드 블록 감싸기(```) 없이 문서 내용만.
"""

_BASE_INFO_SECTION_TEMPLATE = """\
## 참고 자료 (기반정보 문서)
이 문서는 사용자 피드백과 무관하게 유지되는 범용 참조 자료입니다.
개선 시 이 자료와 일관성이 유지되도록 하세요.

{base_info_document}
"""


# ---------------------------------------------------------------------------
# LLM 호출
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 공개 API · apply_feedback
# ---------------------------------------------------------------------------

def apply_feedback(
    current_doc: Dict[str, Any],
    user_feedback: str,
    raw_input: str = "",
    base_info_doc: Optional[Dict[str, Any]] = None,
) -> FeedbackResult:
    """
    사용자 피드백을 현재 문서에 적용해 새 버전 생성.

    Args:
      current_doc: 현재 버전 문서 {"document": str, "created_at": str}
      user_feedback: 사용자 피드백 텍스트
      raw_input: 원본 사용자 요청 (컨텍스트)
      base_info_doc: Phase 3a 기반정보 문서 (선택, 있으면 일관성 체크용)

    Returns:
      FeedbackResult (예외 전파 없음)

    실패 정책:
      - 입력 유효성 실패 → FeedbackResult(status=failed, error=...)
      - LLM 호출 실패 → FeedbackResult(status=failed, new_doc=None)
        * 호출자는 기존 current_doc을 유지
    """
    # 1. 입력 검증
    if not isinstance(current_doc, dict) or not current_doc.get("document", "").strip():
        return FeedbackResult(
            status=STATUS_FAILED,
            error="current_doc이 비어있거나 유효하지 않음",
            feedback_applied=user_feedback,
        )

    if not isinstance(user_feedback, str) or not user_feedback.strip():
        return FeedbackResult(
            status=STATUS_FAILED,
            error="user_feedback이 비어있음",
            feedback_applied=None,
        )

    # 2. 프롬프트 구성
    base_info_section = ""
    if base_info_doc and isinstance(base_info_doc, dict):
        base_info_text = base_info_doc.get("document", "").strip()
        if base_info_text:
            base_info_section = _BASE_INFO_SECTION_TEMPLATE.format(
                base_info_document=base_info_text
            )

    prompt = _PROMPT_APPLY_FEEDBACK.format(
        raw_input=raw_input.strip() if raw_input else "(원본 요청 없음)",
        current_document=current_doc["document"].strip(),
        user_feedback=user_feedback.strip(),
        base_info_section=base_info_section,
    )

    # 3. LLM 호출
    new_text = call_llm(prompt, FEEDBACK_MODEL, FEEDBACK_TIMEOUT)

    if new_text is None:
        return FeedbackResult(
            status=STATUS_FAILED,
            error="LLM 호출 실패 또는 API 키 없음",
            feedback_applied=user_feedback,
        )

    if not new_text.strip():
        return FeedbackResult(
            status=STATUS_FAILED,
            error="LLM 응답이 비어있음",
            feedback_applied=user_feedback,
        )

    # 4. 새 문서 구성
    new_doc = {
        "document": new_text,
        "created_at": utc_now_iso(),
    }

    return FeedbackResult(
        status=STATUS_SUCCESS,
        new_doc=new_doc,
        feedback_applied=user_feedback.strip(),
        error=None,
    )


# ---------------------------------------------------------------------------
# 공개 API · append_version
# ---------------------------------------------------------------------------

def append_version(
    existing_versions: Optional[List[Dict[str, Any]]],
    new_doc: Dict[str, Any],
    feedback_applied: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    새 버전을 이력 리스트에 추가.

    각 버전 엔트리 스키마:
      {
        "version": int,              # 1부터 증가
        "document": str,             # 문서 본문
        "feedback_applied": str|None,# 적용된 피드백 (v1은 None)
        "created_at": str,           # ISO 시각
      }

    Args:
      existing_versions: 기존 버전 이력 (None 또는 [])
      new_doc: 추가할 새 문서 {"document": str, "created_at": str}
      feedback_applied: 이 버전이 반영한 피드백 (첫 버전이면 None)

    Returns:
      업데이트된 버전 리스트 (새 객체, 원본 불변)

    Raises:
      ValueError: new_doc이 유효하지 않음
    """
    if not isinstance(new_doc, dict) or not new_doc.get("document", "").strip():
        raise ValueError("new_doc이 비어있거나 유효하지 않음")

    versions = list(existing_versions or [])

    # 다음 버전 번호 계산
    max_version = 0
    for v in versions:
        if isinstance(v, dict):
            vnum = v.get("version", 0)
            if isinstance(vnum, int) and vnum > max_version:
                max_version = vnum
    next_version = max_version + 1

    entry = {
        "version": next_version,
        "document": new_doc["document"],
        "feedback_applied": feedback_applied,
        "created_at": new_doc.get("created_at") or utc_now_iso(),
    }
    versions.append(entry)
    return versions


# ---------------------------------------------------------------------------
# 공개 API · confirm_final
# ---------------------------------------------------------------------------

def confirm_final(final_doc: Dict[str, Any]) -> ConfirmResult:
    """
    최종 버전 확정 — Phase 6 진입 가능 신호.

    Args:
      final_doc: 확정할 문서 {"document": str, "created_at": str}

    Returns:
      ConfirmResult (예외 전파 없음)
    """
    if not isinstance(final_doc, dict):
        return ConfirmResult(
            confirmed=False,
            error="final_doc이 dict가 아님",
        )

    doc_text = final_doc.get("document", "")
    if not isinstance(doc_text, str) or not doc_text.strip():
        return ConfirmResult(
            confirmed=False,
            error="final_doc.document가 비어있음",
        )

    return ConfirmResult(
        confirmed=True,
        final_doc=final_doc,
        confirmed_at=utc_now_iso(),
        error=None,
    )


# ---------------------------------------------------------------------------
# 유틸 · 최근 N개만 가져오기 (UI 표시용)
# ---------------------------------------------------------------------------

def get_recent_versions(
    versions: List[Dict[str, Any]],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    버전 이력에서 최근 N개 반환 (scope.md v4 결정사항 #4).
    DB 저장은 무제한, UI 표시는 limit 제한.

    Args:
      versions: 전체 버전 이력
      limit: 최대 반환 개수 (기본 10)

    Returns:
      최근 N개 (version 번호 내림차순)
    """
    if not versions:
        return []
    sorted_vs = sorted(
        (v for v in versions if isinstance(v, dict)),
        key=lambda v: v.get("version", 0),
        reverse=True,
    )
    return sorted_vs[:max(0, limit)]
