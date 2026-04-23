"""
src/utils/budget_guard.py — 프로젝트별 LLM 비용 가드 (Step 14-1)

역할:
  - 프로젝트 1회 실행에 사용 가능한 비용 상한 관리
  - 호출 전 예산 체크, 호출 후 비용 차감
  - 상한 도달 시 후속 LLM 호출 차단 (조용히 None 반환 유도)

사용법:
  guard = BudgetGuard(project_id="proj-xxxx")
  if guard.can_afford(estimated=1.5):
      text = call_llm(prompt, model, timeout, budget_guard=guard)
      guard.consume(actual_cost_usd)

환경변수:
  BUDGET_PROJECT_MAX_USD  — 프로젝트당 상한 (기본 5.0)

설계 원칙:
  - 메모리 단위 dataclass (DB 영속화는 Step 14-1 비용 추적과 연계 예정)
  - 예외 전파 없음: 초과 시 exceeded() True 반환, 호출자가 처리
  - 하위 호환: None으로 넘기면 검사 없이 동작 (기존 call_llm 그대로 쓸 수 있음)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _default_max_usd() -> float:
    """환경변수 BUDGET_PROJECT_MAX_USD 를 float로 안전하게 파싱."""
    raw = os.environ.get("BUDGET_PROJECT_MAX_USD", "5.0")
    try:
        value = float(raw)
        return max(0.0, value)
    except (ValueError, TypeError):
        return 5.0


@dataclass
class BudgetGuard:
    """
    프로젝트 단위 비용 상한 추적기.

    Attributes:
      project_id: 소속 프로젝트 식별자
      max_cost_usd: 허용 최대 비용 (USD). 환경변수 기본값 사용.
      current_cost: 누적된 비용 (USD).

    Properties:
      remaining: 남은 예산 (USD, 0 이상 보장).

    Methods:
      exceeded(): 상한 도달 여부.
      can_afford(estimated): 추정 비용을 감당 가능한지.
      consume(cost): 실제 비용 누적.
      to_dict(): DB 저장/UI 표시용 딕셔너리.
    """
    project_id: str
    max_cost_usd: float = field(default_factory=_default_max_usd)
    current_cost: float = 0.0

    # ---------------------------------------------------------------------
    # 조회
    # ---------------------------------------------------------------------

    @property
    def remaining(self) -> float:
        """남은 예산 (USD). 음수는 0으로 clamp."""
        return max(0.0, self.max_cost_usd - self.current_cost)

    def exceeded(self) -> bool:
        """상한 도달 여부 (같거나 초과하면 True)."""
        return self.current_cost >= self.max_cost_usd

    def can_afford(self, estimated: float) -> bool:
        """
        추정 비용을 감당 가능한지.

        음수 estimated는 0으로 간주 (안전장치).
        """
        if estimated is None or estimated < 0:
            estimated = 0.0
        return (self.current_cost + estimated) <= self.max_cost_usd

    # ---------------------------------------------------------------------
    # 변경
    # ---------------------------------------------------------------------

    def consume(self, cost: float) -> None:
        """
        실제 비용 누적. None/음수는 무시 (방어적 처리).

        상한 초과해도 기록은 함 (사후 분석용).
        """
        if cost is None or cost < 0:
            return
        self.current_cost += cost

    def reset(self) -> None:
        """누적 비용 초기화. 재실행용."""
        self.current_cost = 0.0

    # ---------------------------------------------------------------------
    # 직렬화
    # ---------------------------------------------------------------------

    def to_dict(self) -> dict:
        """UI/DB 표시용. 소수점 4자리로 반올림."""
        return {
            "project_id": self.project_id,
            "max_cost_usd": round(self.max_cost_usd, 4),
            "current_cost": round(self.current_cost, 4),
            "remaining": round(self.remaining, 4),
            "exceeded": self.exceeded(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BudgetGuard":
        """DB에서 복원. 누락 필드는 기본값."""
        return cls(
            project_id=data.get("project_id", ""),
            max_cost_usd=float(data.get("max_cost_usd", _default_max_usd())),
            current_cost=float(data.get("current_cost", 0.0)),
        )
