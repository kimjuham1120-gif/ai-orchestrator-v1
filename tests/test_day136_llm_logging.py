"""
Day 136 — call_llm 자동 로깅 테스트 (Step 14-1 단계 3)

테스트 포인트:
  1. 컨텍스트 없으면 로깅 안 함 (하위호환)
  2. 컨텍스트 있으면 llm_calls 테이블에 INSERT
  3. usage 필드에서 토큰 파싱
  4. cached 여부 로깅
  5. 실패 호출도 로깅 (status=failed)
  6. 4xx 에러 로깅
  7. 로깅 실패해도 본 호출엔 영향 없음
  8. set_llm_context / clear_llm_context 동작
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.utils.llm_utils import (
    call_llm,
    set_llm_context,
    clear_llm_context,
    get_llm_context,
    LLMContext,
)
from src.store.artifact_store import get_run_llm_calls


_HTTPX_PATCH = "src.utils.llm_utils.httpx.post"


def _db_path(tmp_path):
    return str(tmp_path / "test.db")


def _mock_success_response(content="응답 텍스트", usage=None):
    """성공 응답 mock. usage 포함 가능."""
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()

    body = {
        "choices": [{"message": {"content": content}}],
    }
    if usage is not None:
        body["usage"] = usage
    response.json.return_value = body
    return response


def _mock_4xx_response(status=400):
    response = MagicMock()
    response.status_code = status
    response.raise_for_status = MagicMock()
    return response


@pytest.fixture(autouse=True)
def _clear_context():
    """각 테스트 전후로 컨텍스트 초기화 (테스트 간 오염 방지)."""
    clear_llm_context()
    yield
    clear_llm_context()


# ===========================================================================
# 1. 컨텍스트 없으면 로깅 안 함
# ===========================================================================

class TestNoContextNoLogging:
    def test_call_llm_without_context_does_not_log(self, tmp_path, monkeypatch):
        """컨텍스트 설정 안 하면 DB에 기록 없음 (하위호환 보장)."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        db = _db_path(tmp_path)
        # DB는 존재하지만 컨텍스트 미설정

        with patch(_HTTPX_PATCH, return_value=_mock_success_response("x")):
            result = call_llm("prompt", "model", 30.0)
            assert result == "x"

        # DB에 아무 기록 없어야
        calls = get_run_llm_calls(db, "any-run")
        assert calls == []

    def test_call_llm_works_without_db(self, monkeypatch):
        """DB 경로 없어도 call_llm은 그냥 동작."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_HTTPX_PATCH, return_value=_mock_success_response("hi")):
            result = call_llm("p", "m", 10.0)
            assert result == "hi"


# ===========================================================================
# 2. 컨텍스트 설정 후 로깅
# ===========================================================================

class TestContextLogging:
    def test_sets_and_gets_context(self, tmp_path):
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p1", run_id="r1", phase="0.5")

        ctx = get_llm_context()
        assert ctx is not None
        assert ctx.db_path == db
        assert ctx.project_id == "p1"
        assert ctx.run_id == "r1"
        assert ctx.phase == "0.5"

    def test_clear_context(self, tmp_path):
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="1")
        assert get_llm_context() is not None

        clear_llm_context()
        assert get_llm_context() is None

    def test_empty_db_path_clears(self, tmp_path):
        """빈 db_path 주면 컨텍스트 해제 효과."""
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="1")
        set_llm_context(db_path="")
        assert get_llm_context() is None

    def test_successful_call_logged(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p1", run_id="r1", phase="0.5")

        usage = {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
        }

        with patch(_HTTPX_PATCH, return_value=_mock_success_response("ok", usage=usage)):
            call_llm("test prompt", "anthropic/claude-haiku-4-5", 30.0)

        calls = get_run_llm_calls(db, "r1")
        assert len(calls) == 1
        call = calls[0]
        assert call["project_id"] == "p1"
        assert call["phase"] == "0.5"
        assert call["model"] == "anthropic/claude-haiku-4-5"
        assert call["prompt_tokens"] == 1000
        assert call["completion_tokens"] == 500
        assert call["total_tokens"] == 1500
        assert call["status"] == "success"

    def test_cost_calculated_from_model_pricing(self, tmp_path, monkeypatch):
        """model_pricing 기준으로 cost 계산되어 기록."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="3a")

        # Sonnet 4.6 @ 1000 input + 500 output = (1000×3 + 500×15) / 1M = 0.0105
        usage = {"prompt_tokens": 1000, "completion_tokens": 500}
        with patch(_HTTPX_PATCH, return_value=_mock_success_response("x", usage=usage)):
            call_llm("p", "anthropic/claude-sonnet-4-6", 30.0)

        calls = get_run_llm_calls(db, "r")
        assert calls[0]["cost_usd"] == pytest.approx(0.0105, abs=1e-6)

    def test_multiple_calls_accumulate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="4-audit")

        usage = {"prompt_tokens": 100, "completion_tokens": 50}
        with patch(_HTTPX_PATCH, return_value=_mock_success_response("x", usage=usage)):
            call_llm("p1", "anthropic/claude-haiku-4-5", 30.0)
            call_llm("p2", "anthropic/claude-haiku-4-5", 30.0)
            call_llm("p3", "anthropic/claude-haiku-4-5", 30.0)

        calls = get_run_llm_calls(db, "r")
        assert len(calls) == 3


# ===========================================================================
# 3. cached 플래그 기록
# ===========================================================================

class TestCachedFlagLogging:
    def test_short_prompt_not_cached(self, tmp_path, monkeypatch):
        """짧은 프롬프트는 cache_control 없음 → cached=False로 기록."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("PROMPT_CACHE_ENABLED", "true")
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="0.5")

        short_prompt = "short"
        usage = {"prompt_tokens": 10, "completion_tokens": 5}
        with patch(_HTTPX_PATCH, return_value=_mock_success_response("x", usage=usage)):
            call_llm(short_prompt, "anthropic/claude-sonnet-4-6", 30.0)

        calls = get_run_llm_calls(db, "r")
        assert calls[0]["cached"] is False

    def test_long_prompt_cached_flag_true(self, tmp_path, monkeypatch):
        """긴 프롬프트(4000자 이상)는 cache_control 적용 → cached=True."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("PROMPT_CACHE_ENABLED", "true")
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="3a")

        long_prompt = "x" * 5000
        usage = {"prompt_tokens": 1500, "completion_tokens": 500}
        with patch(_HTTPX_PATCH, return_value=_mock_success_response("y", usage=usage)):
            call_llm(long_prompt, "anthropic/claude-sonnet-4-6", 30.0)

        calls = get_run_llm_calls(db, "r")
        assert calls[0]["cached"] is True

    def test_cache_disabled_globally(self, tmp_path, monkeypatch):
        """PROMPT_CACHE_ENABLED=false면 긴 프롬프트도 cached=False."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("PROMPT_CACHE_ENABLED", "false")
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="3a")

        long_prompt = "x" * 5000
        usage = {"prompt_tokens": 1500, "completion_tokens": 500}
        with patch(_HTTPX_PATCH, return_value=_mock_success_response("y", usage=usage)):
            call_llm(long_prompt, "anthropic/claude-sonnet-4-6", 30.0)

        calls = get_run_llm_calls(db, "r")
        assert calls[0]["cached"] is False


# ===========================================================================
# 4. 실패 호출 로깅
# ===========================================================================

class TestFailureLogging:
    def test_4xx_error_logged_as_failed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="0.5")

        with patch(_HTTPX_PATCH, return_value=_mock_4xx_response(400)):
            result = call_llm("p", "m", 30.0)
            assert result is None

        calls = get_run_llm_calls(db, "r")
        assert len(calls) == 1
        assert calls[0]["status"] == "failed"
        assert calls[0]["error"] is not None
        assert "400" in calls[0]["error"]

    def test_network_exception_logged_after_retries(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="1")

        import httpx as _httpx
        # _RETRY_DELAYS를 0으로 monkeypatch해서 테스트 속도 확보
        monkeypatch.setattr("src.utils.llm_utils._RETRY_DELAYS", [0.0, 0.0])

        with patch(_HTTPX_PATCH, side_effect=_httpx.ConnectError("refused")):
            result = call_llm("p", "m", 30.0)
            assert result is None

        calls = get_run_llm_calls(db, "r")
        # 3번 시도했지만 로깅은 최종 실패 1번만
        assert len(calls) == 1
        assert calls[0]["status"] == "failed"
        assert "ConnectError" in calls[0]["error"]

    def test_failed_call_still_has_duration(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="0.5")

        with patch(_HTTPX_PATCH, return_value=_mock_4xx_response(400)):
            call_llm("p", "m", 30.0)

        calls = get_run_llm_calls(db, "r")
        assert calls[0]["duration_ms"] >= 0  # 음수 아님


# ===========================================================================
# 5. 에러 복원력
# ===========================================================================

class TestErrorResilience:
    def test_bad_db_path_does_not_break_call(self, monkeypatch):
        """DB 경로가 잘못돼도 call_llm 자체는 동작."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        set_llm_context(
            db_path="/absolutely/nonexistent/path/db.sqlite",
            project_id="p", run_id="r", phase="0.5",
        )

        with patch(_HTTPX_PATCH, return_value=_mock_success_response("answer")):
            result = call_llm("p", "m", 30.0)
            # 로깅은 실패하지만 본 호출은 성공
            assert result == "answer"

    def test_no_usage_field_still_logs(self, tmp_path, monkeypatch):
        """응답에 usage 필드 없어도 로깅은 됨 (토큰 0으로)."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="0.5")

        # usage 없는 응답
        with patch(_HTTPX_PATCH, return_value=_mock_success_response("x", usage=None)):
            call_llm("p", "m", 30.0)

        calls = get_run_llm_calls(db, "r")
        assert len(calls) == 1
        assert calls[0]["prompt_tokens"] == 0
        assert calls[0]["completion_tokens"] == 0
        assert calls[0]["status"] == "success"  # 토큰 없어도 성공은 성공

    def test_partial_usage_field(self, tmp_path, monkeypatch):
        """usage에 일부 필드만 있을 때."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="0.5")

        # completion_tokens만 있음
        usage = {"completion_tokens": 100}
        with patch(_HTTPX_PATCH, return_value=_mock_success_response("x", usage=usage)):
            call_llm("p", "m", 30.0)

        calls = get_run_llm_calls(db, "r")
        assert calls[0]["prompt_tokens"] == 0
        assert calls[0]["completion_tokens"] == 100


# ===========================================================================
# 6. 컨텍스트 격리
# ===========================================================================

class TestContextIsolation:
    def test_context_persists_across_calls(self, tmp_path, monkeypatch):
        """한 번 설정한 컨텍스트로 여러 호출."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        db = _db_path(tmp_path)
        set_llm_context(db_path=db, project_id="p", run_id="r", phase="2")

        usage = {"prompt_tokens": 50, "completion_tokens": 25}
        with patch(_HTTPX_PATCH, return_value=_mock_success_response("x", usage=usage)):
            for _ in range(5):
                call_llm("p", "m", 30.0)

        calls = get_run_llm_calls(db, "r")
        assert len(calls) == 5
        # 전부 같은 phase
        assert all(c["phase"] == "2" for c in calls)

    def test_context_change_affects_subsequent_calls(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        db = _db_path(tmp_path)

        usage = {"prompt_tokens": 10, "completion_tokens": 5}
        with patch(_HTTPX_PATCH, return_value=_mock_success_response("x", usage=usage)):
            # Phase 0.5
            set_llm_context(db_path=db, project_id="p", run_id="r", phase="0.5")
            call_llm("p", "m", 30.0)

            # Phase 1로 변경
            set_llm_context(db_path=db, project_id="p", run_id="r", phase="1")
            call_llm("p", "m", 30.0)

        calls = get_run_llm_calls(db, "r")
        assert len(calls) == 2
        assert calls[0]["phase"] == "0.5"
        assert calls[1]["phase"] == "1"


# ===========================================================================
# 7. 실사용 시나리오
# ===========================================================================

class TestRealisticScenarios:
    def test_full_phase_workflow(self, tmp_path, monkeypatch):
        """Phase 0.5 → 1 → 3a → 3b 시뮬레이션."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        db = _db_path(tmp_path)

        usage = {"prompt_tokens": 500, "completion_tokens": 300}
        with patch(_HTTPX_PATCH, return_value=_mock_success_response("x", usage=usage)):
            # 각 Phase 진입 시 컨텍스트 갱신
            for phase, model in [
                ("0.5", "anthropic/claude-haiku-4-5"),
                ("1",   "anthropic/claude-haiku-4-5"),
                ("3a",  "anthropic/claude-sonnet-4-6"),
                ("3b",  "anthropic/claude-sonnet-4-6"),
            ]:
                set_llm_context(
                    db_path=db, project_id="proj-x",
                    run_id="run-1", phase=phase,
                )
                call_llm("prompt", model, 30.0)

        calls = get_run_llm_calls(db, "run-1")
        assert len(calls) == 4
        phases = [c["phase"] for c in calls]
        assert phases == ["0.5", "1", "3a", "3b"]

        # 비용 합계 확인
        from src.store.artifact_store import get_project_total_cost
        total = get_project_total_cost(db, "proj-x")
        assert total > 0
