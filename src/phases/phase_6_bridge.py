"""
Phase 6 · 트랙 전환 결정 (Day 118~)

역할: Phase 5(사용자 검수) 통과 후, 다음 행동을 결정하는 게이트.
  - document_done → 프로젝트 종료 (문서 완료)
  - app_dev       → Phase 7 앱개발 진입 (target_doc → deliverable_spec 변환)
  - cancel        → 프로젝트 중단

입력:
  user_decision: str                사용자 선택 (document_done / app_dev / cancel)
  raw_input: str                    원본 요청 (컨텍스트용)
  target_doc: Optional[dict]        Phase 3b 결과 (app_dev 선택 시 필수)

출력:
  BridgeDecision:
    decision: str                   승인된 결정
    next_phase: Optional[str]       다음 단계 이름 ("phase_7" / None)
    deliverable_spec: Optional[dict]  앱개발 선택 시 변환 결과
    error: Optional[str]
    reason: str                     결정 근거 메시지

설계 원칙:
  - 사용자 명시 결정 필수 (자동 판정 없음)
  - 앱개발 선택 시 target_doc 검증 엄격 (없으면 실패)
  - deliverable_spec 형식은 v3 스키마 그대로 유지 (Phase 7 호환)
  - v3 lane_selector/flow_router와 별개 동작 (Step 12에서 기존 것 삭제)

연관 파일:
  - Step 12에서 삭제 예정: src/interpreter/lane_selector.py
  - Step 12에서 삭제 예정: src/interpreter/flow_router.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# 결정 상수
# ---------------------------------------------------------------------------

DECISION_DOCUMENT_DONE = "document_done"
DECISION_APP_DEV = "app_dev"
DECISION_CANCEL = "cancel"

_VALID_DECISIONS = {DECISION_DOCUMENT_DONE, DECISION_APP_DEV, DECISION_CANCEL}

NEXT_PHASE_7 = "phase_7"
NEXT_PHASE_END = None


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

@dataclass
class BridgeDecision:
    """Phase 6 트랙 전환 결정 결과."""
    decision: str                                       # document_done / app_dev / cancel / invalid
    next_phase: Optional[str] = None                    # "phase_7" or None
    deliverable_spec: Optional[Dict[str, Any]] = None   # app_dev일 때만 채워짐
    reason: str = ""                                    # 사용자에게 표시 가능한 근거
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "next_phase": self.next_phase,
            "deliverable_spec": self.deliverable_spec,
            "reason": self.reason,
            "error": self.error,
        }

    @property
    def is_valid(self) -> bool:
        """유효한 결정이며 에러 없는 상태."""
        return self.error is None and self.decision in _VALID_DECISIONS


# ---------------------------------------------------------------------------
# target_doc → deliverable_spec 변환
# ---------------------------------------------------------------------------

def convert_target_doc_to_spec(
    target_doc: Dict[str, Any],
    raw_input: str,
) -> Dict[str, Any]:
    """
    Phase 3b의 target_doc을 Phase 7이 사용할 deliverable_spec 형태로 변환.

    v3 deliverable_spec 스키마:
      {
        "goal": str,
        "description": str,
        "target_files": list[str],
        "constraints": list[str],
        "source": "phase_3_target_doc"
      }

    Args:
      target_doc: {"document": str, "created_at": str}
      raw_input: 원본 사용자 요청

    Returns:
      deliverable_spec dict (Phase 7이 그대로 사용 가능)

    Raises:
      ValueError: target_doc이 유효하지 않음
    """
    if not target_doc or not isinstance(target_doc, dict):
        raise ValueError("target_doc이 비어있거나 dict가 아님")

    document = target_doc.get("document", "")
    if not isinstance(document, str) or not document.strip():
        raise ValueError("target_doc.document가 비어있음")

    # deliverable_spec 구성 — v3 스키마 호환
    spec = {
        "goal": raw_input.strip() if raw_input else "(원본 요청 없음)",
        "description": document.strip(),
        "target_files": [],  # Phase 7 planner가 채움
        "constraints": [
            "Phase 3b에서 생성된 target_doc을 기반으로 한다",
            "사용자 원본 요청의 의도를 유지한다",
        ],
        "source": "phase_3_target_doc",
        "created_from": {
            "raw_input": raw_input,
            "target_doc_created_at": target_doc.get("created_at"),
        },
    }
    return spec


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def decide_track(
    user_decision: str,
    raw_input: str = "",
    target_doc: Optional[Dict[str, Any]] = None,
) -> BridgeDecision:
    """
    Phase 6 · 트랙 전환 결정 (공개 API).

    사용자 선택을 받아 다음 트랙 결정. 자동 판정 없음.

    Args:
      user_decision: "document_done" | "app_dev" | "cancel"
      raw_input: 원본 사용자 요청 (app_dev 선택 시 spec 생성에 사용)
      target_doc: Phase 3b 결과 (app_dev 선택 시 필수)

    Returns:
      BridgeDecision (예외 전파 없음 — is_valid / error 필드로 판단)

    호출 예:
        d = decide_track("app_dev", raw_input, target_doc)
        if d.is_valid and d.next_phase == "phase_7":
            # Phase 7 진입
            spec = d.deliverable_spec
    """
    # 1. 입력 정규화
    if user_decision is None:
        user_decision = ""
    decision = str(user_decision).strip().lower()

    # 2. 유효성 검증
    if decision not in _VALID_DECISIONS:
        return BridgeDecision(
            decision="invalid",
            next_phase=None,
            reason=f"알 수 없는 결정: {user_decision!r}",
            error=(
                f"user_decision은 {sorted(_VALID_DECISIONS)} 중 하나여야 합니다. "
                f"받은 값: {user_decision!r}"
            ),
        )

    # 3. 분기 처리
    if decision == DECISION_DOCUMENT_DONE:
        return BridgeDecision(
            decision=DECISION_DOCUMENT_DONE,
            next_phase=NEXT_PHASE_END,
            reason="문서 산출물이 확정되어 프로젝트를 종료합니다.",
        )

    if decision == DECISION_CANCEL:
        return BridgeDecision(
            decision=DECISION_CANCEL,
            next_phase=NEXT_PHASE_END,
            reason="사용자가 프로젝트를 취소했습니다.",
        )

    # 4. app_dev — target_doc 검증 필수
    if decision == DECISION_APP_DEV:
        if target_doc is None:
            return BridgeDecision(
                decision=DECISION_APP_DEV,
                next_phase=None,
                reason="앱개발 트랙에는 Phase 3b target_doc이 필요합니다.",
                error="target_doc이 None — 앱개발 트랙 진입 불가",
            )

        try:
            spec = convert_target_doc_to_spec(target_doc, raw_input)
        except ValueError as exc:
            return BridgeDecision(
                decision=DECISION_APP_DEV,
                next_phase=None,
                reason="target_doc을 deliverable_spec으로 변환할 수 없습니다.",
                error=f"변환 실패: {exc}",
            )

        return BridgeDecision(
            decision=DECISION_APP_DEV,
            next_phase=NEXT_PHASE_7,
            deliverable_spec=spec,
            reason="앱개발 트랙으로 진입 — target_doc을 deliverable_spec으로 변환 완료.",
        )

    # 도달 불가 (위 분기가 모두 커버)
    return BridgeDecision(
        decision="invalid",
        next_phase=None,
        error="내부 로직 오류",
        reason="",
    )
