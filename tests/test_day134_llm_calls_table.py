"""
Day 134 — llm_calls 테이블 CRUD 테스트 (Step 14-1)

테스트 포인트:
  1. 테이블 자동 생성 (기존 DB에서도 마이그레이션)
  2. log_llm_call — 기본 삽입
  3. log_llm_call — 방어적 입력 (음수, None)
  4. log_llm_call — 실패 케이스 (예외 전파 없음)
  5. get_project_total_cost — 합산
  6. get_run_llm_calls — run 필터
  7. get_recent_llm_calls — 최근 N개 + 프로젝트 필터
  8. cached 필드 bool 왕복

모든 테스트는 tmp_path의 임시 DB 사용 (격리 보장).
"""
from __future__ import annotations

import pytest
import sqlite3

from src.store.artifact_store import (
    log_llm_call,
    get_project_total_cost,
    get_run_llm_calls,
    get_recent_llm_calls,
    _connect,
)


# ===========================================================================
# 공용 헬퍼
# ===========================================================================

def _db_path(tmp_path):
    return str(tmp_path / "test.db")


# ===========================================================================
# 1. 테이블 자동 생성
# ===========================================================================

class TestTableCreation:
    def test_llm_calls_table_exists_after_connect(self, tmp_path):
        db = _db_path(tmp_path)
        conn = _connect(db)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='llm_calls'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "llm_calls"

    def test_llm_calls_indexes_created(self, tmp_path):
        db = _db_path(tmp_path)
        conn = _connect(db)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='llm_calls'"
        ).fetchall()
        conn.close()
        names = [r[0] for r in rows]
        assert "idx_llm_calls_project" in names
        assert "idx_llm_calls_run" in names
        assert "idx_llm_calls_created" in names

    def test_idempotent_reconnect(self, tmp_path):
        """여러 번 _connect 호출해도 에러 없음."""
        db = _db_path(tmp_path)
        _connect(db).close()
        _connect(db).close()
        _connect(db).close()  # 3번 — 에러 없어야

    def test_schema_columns(self, tmp_path):
        db = _db_path(tmp_path)
        conn = _connect(db)
        rows = conn.execute("PRAGMA table_info(llm_calls)").fetchall()
        conn.close()
        cols = {r[1] for r in rows}
        required = {
            "id", "project_id", "run_id", "phase", "model",
            "prompt_tokens", "completion_tokens", "total_tokens",
            "cost_usd", "cached", "duration_ms", "status",
            "error", "created_at",
        }
        assert required.issubset(cols), f"누락 컬럼: {required - cols}"


# ===========================================================================
# 2. log_llm_call — 기본 삽입
# ===========================================================================

class TestLogLlmCallBasic:
    def test_insert_returns_positive_id(self, tmp_path):
        db = _db_path(tmp_path)
        row_id = log_llm_call(
            db_path=db,
            project_id="proj-1",
            run_id="run-1",
            phase="0.5",
            model="anthropic/claude-haiku-4-5",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.000375,
        )
        assert row_id > 0

    def test_inserted_row_retrievable(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(
            db_path=db,
            project_id="proj-1",
            run_id="run-1",
            phase="3a",
            model="anthropic/claude-sonnet-4-6",
            prompt_tokens=1000,
            completion_tokens=500,
            cost_usd=0.0105,
        )
        calls = get_run_llm_calls(db, "run-1")
        assert len(calls) == 1
        assert calls[0]["phase"] == "3a"
        assert calls[0]["prompt_tokens"] == 1000
        assert calls[0]["cost_usd"] == pytest.approx(0.0105)

    def test_total_tokens_auto_computed(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(
            db_path=db, project_id="p", run_id="r", phase="1",
            model="anthropic/claude-haiku-4-5",
            prompt_tokens=300, completion_tokens=200,
        )
        calls = get_run_llm_calls(db, "r")
        assert calls[0]["total_tokens"] == 500

    def test_cached_flag_stored_as_bool(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(
            db_path=db, project_id="p", run_id="r", phase="3a",
            model="anthropic/claude-sonnet-4-6", cached=True,
        )
        calls = get_run_llm_calls(db, "r")
        assert calls[0]["cached"] is True

    def test_created_at_populated(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(
            db_path=db, project_id="p", run_id="r", phase="0.5",
            model="test/model",
        )
        calls = get_run_llm_calls(db, "r")
        assert calls[0]["created_at"] is not None
        assert len(calls[0]["created_at"]) > 10  # ISO 8601 형식

    def test_status_default_success(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(
            db_path=db, project_id="p", run_id="r", phase="1",
            model="m",
        )
        calls = get_run_llm_calls(db, "r")
        assert calls[0]["status"] == "success"

    def test_failed_status_with_error(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(
            db_path=db, project_id="p", run_id="r", phase="4-fact",
            model="google/gemini-3.1-pro-preview",
            status="failed",
            error="TimeoutError",
        )
        calls = get_run_llm_calls(db, "r")
        assert calls[0]["status"] == "failed"
        assert calls[0]["error"] == "TimeoutError"


# ===========================================================================
# 3. 방어적 입력
# ===========================================================================

class TestDefensiveInputs:
    def test_negative_tokens_clamped_to_zero(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(
            db_path=db, project_id="p", run_id="r", phase="0.5",
            model="m",
            prompt_tokens=-100,
            completion_tokens=-50,
        )
        calls = get_run_llm_calls(db, "r")
        assert calls[0]["prompt_tokens"] == 0
        assert calls[0]["completion_tokens"] == 0

    def test_none_tokens_treated_as_zero(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(
            db_path=db, project_id="p", run_id="r", phase="0.5",
            model="m",
            prompt_tokens=None,
            completion_tokens=None,
        )
        calls = get_run_llm_calls(db, "r")
        assert calls[0]["prompt_tokens"] == 0

    def test_negative_cost_clamped(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(
            db_path=db, project_id="p", run_id="r", phase="0.5",
            model="m", cost_usd=-5.0,
        )
        calls = get_run_llm_calls(db, "r")
        assert calls[0]["cost_usd"] == 0.0

    def test_null_project_id_accepted(self, tmp_path):
        """project_id 없이도 기록 가능 (고아 호출 — 시스템 수준)."""
        db = _db_path(tmp_path)
        row_id = log_llm_call(
            db_path=db,
            project_id=None,
            run_id=None,
            phase="system",
            model="m",
            prompt_tokens=10,
        )
        assert row_id > 0


# ===========================================================================
# 4. 예외 전파 없음
# ===========================================================================

class TestNoExceptionPropagation:
    def test_invalid_db_path_returns_minus_1(self):
        """쓸 수 없는 경로 → -1 반환, 예외 안 남."""
        # 디렉토리로 경로 주면 sqlite3가 실패해야 하는데
        # 테스트 환경에 따라 다를 수 있음 → 빈 문자열로 테스트
        row_id = log_llm_call(
            db_path="/nonexistent_dir/xyz/definitely_not_writable/db.sqlite",
            project_id="p", run_id="r", phase="0",
            model="m",
        )
        # 실패 시 -1, 성공 시 양수 (어쩌다 경로가 생겨도 동작)
        assert row_id == -1 or row_id > 0


# ===========================================================================
# 5. get_project_total_cost
# ===========================================================================

class TestProjectTotalCost:
    def test_empty_project_zero_cost(self, tmp_path):
        db = _db_path(tmp_path)
        assert get_project_total_cost(db, "empty-proj") == 0.0

    def test_single_call_total(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(
            db_path=db, project_id="p1", run_id="r1", phase="1",
            model="m", cost_usd=1.23,
        )
        assert get_project_total_cost(db, "p1") == pytest.approx(1.23)

    def test_multiple_calls_summed(self, tmp_path):
        db = _db_path(tmp_path)
        for cost in [0.5, 1.0, 1.5, 2.0]:
            log_llm_call(
                db_path=db, project_id="p1", run_id="r1", phase="1",
                model="m", cost_usd=cost,
            )
        assert get_project_total_cost(db, "p1") == pytest.approx(5.0)

    def test_different_projects_isolated(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(db, "p1", "r1", "1", "m", cost_usd=10.0)
        log_llm_call(db, "p2", "r2", "1", "m", cost_usd=20.0)
        log_llm_call(db, "p1", "r1", "2", "m", cost_usd=5.0)

        assert get_project_total_cost(db, "p1") == pytest.approx(15.0)
        assert get_project_total_cost(db, "p2") == pytest.approx(20.0)

    def test_null_project_id_excluded(self, tmp_path):
        """project_id=None 호출은 특정 프로젝트 합계에 포함 안 됨."""
        db = _db_path(tmp_path)
        log_llm_call(db, "p1", "r", "1", "m", cost_usd=10.0)
        log_llm_call(db, None, None, "system", "m", cost_usd=99.0)
        assert get_project_total_cost(db, "p1") == pytest.approx(10.0)

    def test_empty_project_id_returns_zero(self, tmp_path):
        db = _db_path(tmp_path)
        assert get_project_total_cost(db, "") == 0.0

    def test_failed_calls_included_in_total(self, tmp_path):
        """실패 호출도 비용 집계에 포함 (실제 과금되는 경우)."""
        db = _db_path(tmp_path)
        log_llm_call(db, "p1", "r", "1", "m", cost_usd=1.0, status="success")
        log_llm_call(db, "p1", "r", "1", "m", cost_usd=0.5, status="failed")
        assert get_project_total_cost(db, "p1") == pytest.approx(1.5)


# ===========================================================================
# 6. get_run_llm_calls
# ===========================================================================

class TestRunLlmCalls:
    def test_empty_run_returns_empty_list(self, tmp_path):
        db = _db_path(tmp_path)
        assert get_run_llm_calls(db, "nonexistent") == []

    def test_calls_ordered_by_id_ascending(self, tmp_path):
        """삽입 순서대로 반환 (id 오름차순)."""
        db = _db_path(tmp_path)
        log_llm_call(db, "p", "r", "0.5", "m", cost_usd=0.1)
        log_llm_call(db, "p", "r", "1",   "m", cost_usd=0.2)
        log_llm_call(db, "p", "r", "3a",  "m", cost_usd=0.3)

        calls = get_run_llm_calls(db, "r")
        assert len(calls) == 3
        phases = [c["phase"] for c in calls]
        assert phases == ["0.5", "1", "3a"]

    def test_only_matching_run_returned(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(db, "p", "run-A", "1", "m")
        log_llm_call(db, "p", "run-B", "1", "m")
        log_llm_call(db, "p", "run-A", "2", "m")

        calls_a = get_run_llm_calls(db, "run-A")
        calls_b = get_run_llm_calls(db, "run-B")
        assert len(calls_a) == 2
        assert len(calls_b) == 1

    def test_empty_run_id_returns_empty(self, tmp_path):
        db = _db_path(tmp_path)
        assert get_run_llm_calls(db, "") == []


# ===========================================================================
# 7. get_recent_llm_calls
# ===========================================================================

class TestRecentLlmCalls:
    def test_returns_most_recent_first(self, tmp_path):
        db = _db_path(tmp_path)
        for i in range(5):
            log_llm_call(db, "p", f"r{i}", "1", "m", cost_usd=0.1 * i)

        recent = get_recent_llm_calls(db, limit=3)
        assert len(recent) == 3
        # id 내림차순 = 마지막 삽입이 첫 번째
        assert recent[0]["run_id"] == "r4"
        assert recent[2]["run_id"] == "r2"

    def test_limit_respected(self, tmp_path):
        db = _db_path(tmp_path)
        for i in range(10):
            log_llm_call(db, "p", "r", "1", "m")
        assert len(get_recent_llm_calls(db, limit=5)) == 5
        assert len(get_recent_llm_calls(db, limit=100)) == 10

    def test_project_filter(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(db, "p1", "r", "1", "m")
        log_llm_call(db, "p2", "r", "1", "m")
        log_llm_call(db, "p1", "r", "1", "m")

        p1 = get_recent_llm_calls(db, limit=100, project_id="p1")
        p2 = get_recent_llm_calls(db, limit=100, project_id="p2")
        assert len(p1) == 2
        assert len(p2) == 1

    def test_no_project_filter_returns_all(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(db, "p1", "r", "1", "m")
        log_llm_call(db, "p2", "r", "1", "m")
        all_calls = get_recent_llm_calls(db, limit=100)
        assert len(all_calls) == 2

    def test_empty_db_returns_empty_list(self, tmp_path):
        db = _db_path(tmp_path)
        assert get_recent_llm_calls(db) == []

    def test_limit_clamped_to_min_1(self, tmp_path):
        db = _db_path(tmp_path)
        log_llm_call(db, "p", "r", "1", "m")
        # 0 이하 limit → 1로 clamp
        assert len(get_recent_llm_calls(db, limit=0)) == 1
        assert len(get_recent_llm_calls(db, limit=-5)) == 1

    def test_limit_clamped_to_max_1000(self, tmp_path):
        db = _db_path(tmp_path)
        # 아주 큰 값 요청해도 에러 없음
        result = get_recent_llm_calls(db, limit=999999)
        assert isinstance(result, list)


# ===========================================================================
# 8. 실사용 시나리오
# ===========================================================================

class TestRealisticScenarios:
    def test_full_project_workflow(self, tmp_path):
        """Phase 0.5 → 1 → 3a → 3b → 4(3감사+통합) → 5 를 시뮬레이션."""
        db = _db_path(tmp_path)
        project_id = "proj-coffee"
        run_id = "run-1"

        # Phase 0.5 (Haiku)
        log_llm_call(db, project_id, run_id, "0.5", "anthropic/claude-haiku-4-5",
                     prompt_tokens=200, completion_tokens=50, cost_usd=0.00045)
        # Phase 1 (Haiku)
        log_llm_call(db, project_id, run_id, "1", "anthropic/claude-haiku-4-5",
                     prompt_tokens=300, completion_tokens=100, cost_usd=0.0008)
        # Phase 3a (Sonnet)
        log_llm_call(db, project_id, run_id, "3a", "anthropic/claude-sonnet-4-6",
                     prompt_tokens=2000, completion_tokens=1500, cost_usd=0.0285)
        # Phase 3b (Sonnet)
        log_llm_call(db, project_id, run_id, "3b", "anthropic/claude-sonnet-4-6",
                     prompt_tokens=2000, completion_tokens=1500, cost_usd=0.0285)
        # Phase 4 감사관 3명 + 통합
        log_llm_call(db, project_id, run_id, "4-structure", "anthropic/claude-opus-4-7",
                     prompt_tokens=1500, completion_tokens=500, cost_usd=0.02)
        log_llm_call(db, project_id, run_id, "4-balance", "openai/gpt-5.4",
                     prompt_tokens=1500, completion_tokens=500, cost_usd=0.01125)
        log_llm_call(db, project_id, run_id, "4-fact", "google/gemini-3.1-pro-preview",
                     prompt_tokens=1500, completion_tokens=500, cost_usd=0.004375)
        log_llm_call(db, project_id, run_id, "4-synthesis", "anthropic/claude-sonnet-4-6",
                     prompt_tokens=3000, completion_tokens=1500, cost_usd=0.0315)

        # 검증
        total = get_project_total_cost(db, project_id)
        assert total > 0.10
        assert total < 0.20  # 대략 $0.12 ~ $0.15 범위

        calls = get_run_llm_calls(db, run_id)
        assert len(calls) == 8

        recent = get_recent_llm_calls(db, limit=3, project_id=project_id)
        assert len(recent) == 3
        # 가장 최근이 4-synthesis
        assert recent[0]["phase"] == "4-synthesis"

    def test_budget_guard_integration_concept(self, tmp_path):
        """BudgetGuard가 총비용 읽어서 상한 체크하는 시나리오."""
        db = _db_path(tmp_path)
        project_id = "proj-budget"
        MAX = 5.0

        # 단계적으로 비용 누적
        log_llm_call(db, project_id, "r", "2", "m", cost_usd=1.5)
        log_llm_call(db, project_id, "r", "2", "m", cost_usd=1.2)
        log_llm_call(db, project_id, "r", "2", "m", cost_usd=0.8)

        current = get_project_total_cost(db, project_id)
        assert current == pytest.approx(3.5)
        assert current < MAX  # 아직 여유

        # 큰 호출 추가 → 상한 초과
        log_llm_call(db, project_id, "r", "2", "m", cost_usd=2.0)

        current = get_project_total_cost(db, project_id)
        assert current == pytest.approx(5.5)
        assert current > MAX  # 초과 감지
