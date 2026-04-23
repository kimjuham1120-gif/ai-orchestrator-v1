"""
Day 131 — BudgetGuard 단위 테스트 (Step 14-1)

테스트 포인트:
  1. 기본 생성 및 속성
  2. remaining 계산 (clamp 포함)
  3. exceeded 판정 경계값
  4. can_afford 예산 체크 경계값
  5. consume 누적 + 방어적 처리
  6. 환경변수 기본값 적용
  7. reset / to_dict / from_dict 직렬화
"""
from __future__ import annotations

import pytest

from src.utils.budget_guard import BudgetGuard, _default_max_usd


# ===========================================================================
# 1. 기본 생성
# ===========================================================================

class TestCreation:
    def test_minimal_creation(self):
        guard = BudgetGuard(project_id="proj-abc")
        assert guard.project_id == "proj-abc"
        assert guard.current_cost == 0.0
        assert guard.max_cost_usd > 0

    def test_explicit_max_cost(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=10.0)
        assert guard.max_cost_usd == 10.0

    def test_explicit_current_cost(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0, current_cost=1.5)
        assert guard.current_cost == 1.5


# ===========================================================================
# 2. remaining 계산
# ===========================================================================

class TestRemaining:
    def test_initial_remaining_equals_max(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        assert guard.remaining == 5.0

    def test_partial_consumption(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(2.0)
        assert guard.remaining == pytest.approx(3.0)

    def test_exact_exhaustion(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(5.0)
        assert guard.remaining == 0.0

    def test_over_consumption_clamped_to_zero(self):
        """예산 초과해도 remaining은 음수가 되지 않음."""
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(7.5)
        assert guard.remaining == 0.0


# ===========================================================================
# 3. exceeded 판정
# ===========================================================================

class TestExceeded:
    def test_fresh_guard_not_exceeded(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        assert guard.exceeded() is False

    def test_below_max_not_exceeded(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(4.99)
        assert guard.exceeded() is False

    def test_exact_max_is_exceeded(self):
        """경계값: current_cost == max_cost_usd 일 때 exceeded True."""
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(5.0)
        assert guard.exceeded() is True

    def test_over_max_exceeded(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(5.01)
        assert guard.exceeded() is True


# ===========================================================================
# 4. can_afford
# ===========================================================================

class TestCanAfford:
    def test_fresh_can_afford_full_budget(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        assert guard.can_afford(5.0) is True

    def test_cannot_afford_over_budget(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        assert guard.can_afford(5.01) is False

    def test_partial_used_can_afford_remaining(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(3.0)
        assert guard.can_afford(2.0) is True
        assert guard.can_afford(2.01) is False

    def test_zero_estimated_always_ok_when_not_exceeded(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(4.99)
        assert guard.can_afford(0.0) is True

    def test_negative_estimated_treated_as_zero(self):
        """방어적 처리: 음수는 0으로 clamp."""
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(4.99)
        assert guard.can_afford(-1.0) is True

    def test_none_estimated_treated_as_zero(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        assert guard.can_afford(None) is True


# ===========================================================================
# 5. consume 누적 + 방어
# ===========================================================================

class TestConsume:
    def test_multiple_consumes_accumulate(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=10.0)
        guard.consume(1.0)
        guard.consume(2.5)
        guard.consume(0.5)
        assert guard.current_cost == pytest.approx(4.0)

    def test_negative_cost_ignored(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(1.0)
        guard.consume(-0.5)  # 무시되어야
        assert guard.current_cost == pytest.approx(1.0)

    def test_none_cost_ignored(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(1.0)
        guard.consume(None)  # 무시되어야
        assert guard.current_cost == pytest.approx(1.0)

    def test_zero_cost_accepted(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(0.0)
        assert guard.current_cost == 0.0


# ===========================================================================
# 6. 환경변수 기본값
# ===========================================================================

class TestEnvDefault:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("BUDGET_PROJECT_MAX_USD", raising=False)
        guard = BudgetGuard(project_id="p")
        assert guard.max_cost_usd == 5.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("BUDGET_PROJECT_MAX_USD", "12.5")
        guard = BudgetGuard(project_id="p")
        assert guard.max_cost_usd == 12.5

    def test_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("BUDGET_PROJECT_MAX_USD", "not_a_number")
        guard = BudgetGuard(project_id="p")
        assert guard.max_cost_usd == 5.0

    def test_negative_env_clamped_to_zero(self, monkeypatch):
        monkeypatch.setenv("BUDGET_PROJECT_MAX_USD", "-3.0")
        guard = BudgetGuard(project_id="p")
        assert guard.max_cost_usd == 0.0

    def test_helper_function(self, monkeypatch):
        monkeypatch.setenv("BUDGET_PROJECT_MAX_USD", "7.7")
        assert _default_max_usd() == 7.7


# ===========================================================================
# 7. 직렬화
# ===========================================================================

class TestSerialization:
    def test_reset_clears_current_cost(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(3.0)
        guard.reset()
        assert guard.current_cost == 0.0
        assert guard.max_cost_usd == 5.0  # max는 유지

    def test_to_dict_structure(self):
        guard = BudgetGuard(project_id="proj-xyz", max_cost_usd=5.0)
        guard.consume(1.23456)
        d = guard.to_dict()

        assert d["project_id"] == "proj-xyz"
        assert d["max_cost_usd"] == 5.0
        assert d["current_cost"] == 1.2346  # 4자리 반올림
        assert d["remaining"] == 3.7654
        assert d["exceeded"] is False

    def test_to_dict_exceeded_flag(self):
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(6.0)
        d = guard.to_dict()
        assert d["exceeded"] is True
        assert d["remaining"] == 0.0

    def test_from_dict_roundtrip(self):
        original = BudgetGuard(project_id="proj-r", max_cost_usd=8.0)
        original.consume(2.5)

        restored = BudgetGuard.from_dict(original.to_dict())
        assert restored.project_id == "proj-r"
        assert restored.max_cost_usd == 8.0
        assert restored.current_cost == 2.5

    def test_from_dict_missing_fields_use_defaults(self, monkeypatch):
        monkeypatch.setenv("BUDGET_PROJECT_MAX_USD", "5.0")
        restored = BudgetGuard.from_dict({})
        assert restored.project_id == ""
        assert restored.max_cost_usd == 5.0
        assert restored.current_cost == 0.0


# ===========================================================================
# 8. 실사용 시나리오 스모크 테스트
# ===========================================================================

class TestRealisticScenarios:
    def test_phase_2_four_adapters_within_budget(self):
        """4-AI Deep Research 각 $1씩 소비 → $4 총소비 → $5 상한 내."""
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)

        adapters_costs = [1.0, 1.2, 0.8, 1.1]
        for cost in adapters_costs:
            assert guard.can_afford(cost), f"예산 부족: {cost}"
            guard.consume(cost)

        assert guard.current_cost == pytest.approx(4.1)
        assert guard.exceeded() is False
        assert guard.remaining == pytest.approx(0.9)

    def test_phase_2_budget_exhausted_midway(self):
        """3번째 어댑터 호출 시 예산 초과 → 네 번째는 스킵 판정."""
        guard = BudgetGuard(project_id="p", max_cost_usd=3.0)

        guard.consume(1.5)  # 1st
        assert guard.can_afford(1.2) is True
        guard.consume(1.2)  # 2nd
        # 3rd: 남은 예산 0.3, 1.0 필요 → 불가
        assert guard.can_afford(1.0) is False
        # 4th 역시 불가
        assert guard.exceeded() is False  # 아직 $2.7/$3.0
        assert guard.remaining == pytest.approx(0.3)
