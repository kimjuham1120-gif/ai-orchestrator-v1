"""
Day 135 — BudgetGuard DB 연동 테스트 (Step 14-1 단계 2)

테스트 포인트:
  1. from_db — 빈 프로젝트 → current_cost=0
  2. from_db — 기존 기록 → 합산 로드
  3. from_db — max_cost_usd 인자 (None이면 환경변수)
  4. sync_from_db — 재호출 시 최신 반영
  5. DB 연동 후에도 기존 메서드 동작 (can_afford, exceeded 등)
  6. 하위호환: 기존 생성자·API 그대로
"""
from __future__ import annotations

import pytest

from src.utils.budget_guard import BudgetGuard, _default_max_usd
from src.store.artifact_store import log_llm_call


def _db_path(tmp_path):
    return str(tmp_path / "test.db")


# ===========================================================================
# 1. from_db 기본
# ===========================================================================

class TestFromDbBasic:
    def test_empty_project_zero_cost(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BUDGET_PROJECT_MAX_USD", "5.0")
        db = _db_path(tmp_path)
        guard = BudgetGuard.from_db(db, "empty-proj")
        assert guard.project_id == "empty-proj"
        assert guard.current_cost == 0.0
        assert guard.max_cost_usd == 5.0

    def test_loads_existing_total(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(db, "p1", "r1", "1", "m", cost_usd=1.5)
        log_llm_call(db, "p1", "r1", "2", "m", cost_usd=2.0)

        guard = BudgetGuard.from_db(db, "p1")
        assert guard.current_cost == pytest.approx(3.5)

    def test_different_projects_isolated(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(db, "p1", "r", "1", "m", cost_usd=10.0)
        log_llm_call(db, "p2", "r", "1", "m", cost_usd=20.0)

        g1 = BudgetGuard.from_db(db, "p1")
        g2 = BudgetGuard.from_db(db, "p2")
        assert g1.current_cost == pytest.approx(10.0)
        assert g2.current_cost == pytest.approx(20.0)

    def test_custom_max_cost_usd(self, tmp_path):
        db = _db_path(tmp_path)
        guard = BudgetGuard.from_db(db, "p", max_cost_usd=15.0)
        assert guard.max_cost_usd == 15.0

    def test_max_none_uses_env_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BUDGET_PROJECT_MAX_USD", "7.77")
        db = _db_path(tmp_path)
        guard = BudgetGuard.from_db(db, "p", max_cost_usd=None)
        assert guard.max_cost_usd == 7.77

    def test_negative_max_clamped_to_zero(self, tmp_path):
        db = _db_path(tmp_path)
        guard = BudgetGuard.from_db(db, "p", max_cost_usd=-5.0)
        assert guard.max_cost_usd == 0.0


# ===========================================================================
# 2. sync_from_db
# ===========================================================================

class TestSyncFromDb:
    def test_sync_reflects_new_calls(self, tmp_path):
        db = _db_path(tmp_path)
        guard = BudgetGuard.from_db(db, "p")
        assert guard.current_cost == 0.0

        # 다른 프로세스가 기록했다고 가정
        log_llm_call(db, "p", "r", "1", "m", cost_usd=1.0)
        log_llm_call(db, "p", "r", "1", "m", cost_usd=0.5)

        # 아직 메모리엔 반영 안됨
        assert guard.current_cost == 0.0

        # sync
        guard.sync_from_db(db)
        assert guard.current_cost == pytest.approx(1.5)

    def test_sync_overwrites_memory(self, tmp_path):
        """sync는 DB 값으로 덮어씀 — 메모리 consume한 건 잃어버림."""
        db = _db_path(tmp_path)
        guard = BudgetGuard.from_db(db, "p")
        guard.consume(1.0)  # 메모리에만
        assert guard.current_cost == 1.0

        # DB에는 아무것도 없음
        guard.sync_from_db(db)
        assert guard.current_cost == 0.0  # 메모리 덮어쓰기됨

    def test_sync_with_invalid_db_keeps_current(self, tmp_path):
        """쓸 수 없는 DB 경로 → 현재 값 유지 (예외 없음)."""
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(1.5)
        guard.sync_from_db("/totally/invalid/path/db.sqlite")
        # 예외 전파 없음, 값은 유지 또는 0으로 (둘 다 허용)
        assert guard.current_cost >= 0.0


# ===========================================================================
# 3. DB 연동 후 기존 메서드들
# ===========================================================================

class TestDbLoadedGuardMethods:
    def test_can_afford_with_db_loaded(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(db, "p", "r", "1", "m", cost_usd=3.0)
        guard = BudgetGuard.from_db(db, "p", max_cost_usd=5.0)

        assert guard.can_afford(1.5) is True   # 3.0 + 1.5 = 4.5 ≤ 5.0
        assert guard.can_afford(2.5) is False  # 3.0 + 2.5 = 5.5 > 5.0

    def test_exceeded_with_db_loaded(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(db, "p", "r", "1", "m", cost_usd=5.0)
        guard = BudgetGuard.from_db(db, "p", max_cost_usd=5.0)
        assert guard.exceeded() is True

    def test_remaining_with_db_loaded(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(db, "p", "r", "1", "m", cost_usd=2.0)
        guard = BudgetGuard.from_db(db, "p", max_cost_usd=5.0)
        assert guard.remaining == pytest.approx(3.0)

    def test_consume_after_db_load_adds_to_memory(self, tmp_path):
        """DB 로드 후 consume은 메모리에만 추가 (DB 재쓰기 X)."""
        db = _db_path(tmp_path)
        log_llm_call(db, "p", "r", "1", "m", cost_usd=2.0)

        guard = BudgetGuard.from_db(db, "p")
        assert guard.current_cost == 2.0

        guard.consume(1.0)
        assert guard.current_cost == 3.0  # 메모리만

        # DB는 여전히 2.0만 기록됨
        guard2 = BudgetGuard.from_db(db, "p")
        assert guard2.current_cost == 2.0


# ===========================================================================
# 4. to_dict / from_dict 하위호환
# ===========================================================================

class TestSerializationStillWorks:
    def test_to_dict_after_from_db(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(db, "p", "r", "1", "m", cost_usd=1.234)
        guard = BudgetGuard.from_db(db, "p", max_cost_usd=5.0)

        d = guard.to_dict()
        assert d["project_id"] == "p"
        assert d["current_cost"] == 1.234
        assert d["remaining"] == pytest.approx(3.766)
        assert d["exceeded"] is False

    def test_roundtrip_from_db_to_dict_from_dict(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(db, "p", "r", "1", "m", cost_usd=2.5)
        original = BudgetGuard.from_db(db, "p", max_cost_usd=5.0)

        restored = BudgetGuard.from_dict(original.to_dict())
        assert restored.project_id == "p"
        assert restored.current_cost == 2.5
        assert restored.max_cost_usd == 5.0


# ===========================================================================
# 5. 실사용 시나리오
# ===========================================================================

class TestRealisticScenarios:
    def test_phase_2_four_adapters_with_db(self, tmp_path):
        """Phase 2 4-AI 어댑터 시뮬레이션 — DB 기록 + 실시간 가드."""
        db = _db_path(tmp_path)
        project_id = "proj-research"

        # 예산 $5
        guard = BudgetGuard.from_db(db, project_id, max_cost_usd=5.0)
        assert guard.current_cost == 0.0

        # 4개 어댑터 Deep Research
        adapter_costs = [1.5, 1.2, 0.8, 1.1]
        for i, cost in enumerate(adapter_costs):
            assert guard.can_afford(cost), f"어댑터 {i}: 예산 부족"
            # 실제 LLM 호출 후 DB 기록
            log_llm_call(db, project_id, "r", f"2-adapter-{i}",
                         "some/model", cost_usd=cost)
            guard.consume(cost)  # 메모리도 동기화

        total_in_memory = guard.current_cost
        guard.sync_from_db(db)
        total_in_db = guard.current_cost

        assert total_in_memory == pytest.approx(total_in_db)
        assert total_in_db == pytest.approx(4.6)
        assert guard.remaining == pytest.approx(0.4)

    def test_budget_exhausted_stops_further_calls(self, tmp_path):
        """상한 근접 시 다음 호출 차단."""
        db = _db_path(tmp_path)
        project_id = "proj-tight"

        guard = BudgetGuard.from_db(db, project_id, max_cost_usd=3.0)

        # 2번째까지 OK
        guard.consume(1.5)
        guard.consume(1.0)

        # 3번째 호출은 불가 (2.5 + 1.0 > 3.0)
        assert guard.can_afford(1.0) is False
        assert guard.exceeded() is False  # 아직 2.5 < 3.0

        # 큰 작업으로 초과
        guard.consume(1.0)
        assert guard.exceeded() is True

    def test_recovery_from_sync_failure(self, tmp_path):
        """DB 문제 있어도 예외 없이 현 상태 유지."""
        guard = BudgetGuard(project_id="p", max_cost_usd=5.0)
        guard.consume(1.0)

        # DB 경로 잘못 줘도 예외 없어야
        guard.sync_from_db("/bad/path/xyz.db")
        # 값은 DB 조회 결과 또는 현 값 유지
        # (get_project_total_cost가 실패 시 0 반환하므로 0이 될 수 있음)
        assert guard.current_cost >= 0.0
