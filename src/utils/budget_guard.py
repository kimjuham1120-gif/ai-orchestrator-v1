"""
src/utils/budget_guard.py — 프로젝트별 LLM 비용 가드 (Step 14-1)

역할:
  - 프로젝트 1회 실행에 사용 가능한 비용 상한 관리
  - 호출 전 예산 체크, 호출 후 비용 차감
  - 상한 도달 시 후속 LLM 호출 차단 (조용히 None 반환 유도)
  - (Step 14-1 확장) DB 연동: llm_calls 테이블에서 실시간 집계

사용법:
  # 메모리 전용 (테스트·임시)
  guard = BudgetGuard(project_id="proj-xxxx", max_cost_usd=5.0)
  if guard.can_afford(estimated=1.5):
      # call LLM
      guard.consume(actual_cost)

  # DB 연동 (프로덕션 권장)
  guard = BudgetGuard.from_db(db_path, project_id="proj-xxxx")
  # → DB에서 총비용 읽어 current_cost 초기화
  guard.sync_from_db(db_path)
  # → 최신 DB 상태 재반영 (다른 프로세스 기록까지 포함)

환경변수:
  BUDGET_PROJECT_MAX_USD  — 프로젝트당 상한 (기본 5.0)

설계 원칙:
  - 메모리 단위 dataclass
  - 예외 전파 없음: 초과 시 exceeded() True 반환, 호출자가 처리
  - DB 연동은 옵션 (기존 33개 테스트 그대로 유지)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


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
      consume(cost): 실제 비용 누적 (메모리).
      reset(): 누적 비용 초기화.
      to_dict() / from_dict(): 직렬화.
      from_db(): DB에서 현재 비용 로드 (classmethod).
      sync_from_db(): 최신 DB 상태 재반영.
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
        이 메서드는 **메모리만** 변경. DB에는 log_llm_call로 별도 기록.
        """
        if cost is None or cost < 0:
            return
        self.current_cost += cost

    def reset(self) -> None:
        """누적 비용 초기화. 재실행용."""
        self.current_cost = 0.0

    # ---------------------------------------------------------------------
    # DB 연동 (Step 14-1)
    # ---------------------------------------------------------------------

    @classmethod
    def from_db(
        cls,
        db_path: str,
        project_id: str,
        max_cost_usd: float = None,
    ) -> "BudgetGuard":
        """
        DB에서 프로젝트 누적 비용을 읽어 BudgetGuard 생성.

        Args:
          db_path: SQLite DB 경로
          project_id: 프로젝트 식별자
          max_cost_usd: 상한 (None이면 환경변수 기본값)

        Returns:
          current_cost가 DB의 실제 누적액으로 초기화된 인스턴스

        Note:
          llm_calls 테이블이 없으면 current_cost=0.0 으로 반환 (안전).
        """
        # 순환 import 방지: 지연 import
        from src.store.artifact_store import get_project_total_cost

        if max_cost_usd is None:
            max_cost_usd = _default_max_usd()
        max_cost_usd = max(0.0, float(max_cost_usd))

        try:
            current = get_project_total_cost(db_path, project_id)
        except Exception:
            current = 0.0

        return cls(
            project_id=project_id,
            max_cost_usd=max_cost_usd,
            current_cost=current,
        )

    def sync_from_db(self, db_path: str) -> None:
        """
        DB의 최신 상태로 current_cost 재계산.

        긴 워크플로우 중간에 호출하면 다른 프로세스가 기록한 비용까지 반영.
        실패 시 현재 값 유지.
        """
        from src.store.artifact_store import get_project_total_cost

        try:
            self.current_cost = get_project_total_cost(db_path, self.project_id)
        except Exception:
            # DB 조회 실패 시 기존 메모리 값 유지
            pass

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
