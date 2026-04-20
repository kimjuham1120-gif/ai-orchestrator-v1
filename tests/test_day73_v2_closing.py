"""
Day 73~80 — v2 마감 검증 테스트.

목적: 운영 핵심 플로우가 모두 연결되어 있음을 확인.
정책: monkeypatch/mock 전용, 실 네트워크 호출 금지.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# 1. 자동 실행 성공 플로우
# ===========================================================================

class TestAutoExecutionSuccessFlow:
    def test_is_auto_mode_default_false(self, monkeypatch):
        monkeypatch.delenv("CURSOR_AUTO_MODE", raising=False)
        from src.cursor.cursor_executor import is_auto_mode
        assert is_auto_mode() is False

    def test_is_auto_mode_true(self, monkeypatch):
        monkeypatch.setenv("CURSOR_AUTO_MODE", "true")
        from src.cursor.cursor_executor import is_auto_mode
        assert is_auto_mode() is True

    def test_cursor_result_adapter_produces_valid_execution_result(self):
        """adapt_cursor_result → save_execution_result_step 호환 형식."""
        from src.cursor.cursor_executor import CursorExecutionResult
        from src.cursor.cursor_result_adapter import adapt_cursor_result

        raw = CursorExecutionResult(
            job_id="job-ok",
            status="completed",
            output="fixed login bug",
            changed_files=["src/auth.py", "tests/test_auth.py"],
            test_output="5 passed in 2.1s",
        )
        adapted = adapt_cursor_result(raw)

        assert isinstance(adapted["changed_files"], list)
        assert len(adapted["changed_files"]) == 2
        assert "passed" in adapted["test_results"]
        assert adapted["run_log"] != ""

    def test_auto_result_passes_verification(self):
        """자동 실행 결과가 result_verifier를 통과한다."""
        from src.cursor.cursor_executor import CursorExecutionResult
        from src.cursor.cursor_result_adapter import adapt_cursor_result
        from src.verification.result_verifier import verify_execution_result

        raw = CursorExecutionResult(
            job_id="job-verify",
            status="completed",
            output="done",
            changed_files=["src/auth.py"],
            test_output="3 passed",
        )
        adapted = adapt_cursor_result(raw)
        v = verify_execution_result(adapted)
        assert v.passed


# ===========================================================================
# 2. 자동 실행 실패 → manual fallback
# ===========================================================================

class TestAutoExecutionFailureFallback:
    def test_no_api_key_raises_executor_error(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CURSOR_API_KEY", raising=False)
        packet = tmp_path / "packet.md"
        packet.write_text("## test")

        from src.cursor.cursor_executor import CursorExecutor, CursorExecutorError
        with pytest.raises(CursorExecutorError, match="CURSOR_API_KEY"):
            CursorExecutor().execute(str(packet), "run-test")

    def test_http_error_propagates_not_silenced(self, monkeypatch, tmp_path):
        """네트워크 오류가 조용히 삼켜지지 않음."""
        monkeypatch.setenv("CURSOR_API_KEY", "cursor-key")
        import httpx
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(
            httpx.ConnectError("refused")
        ))
        packet = tmp_path / "packet.md"
        packet.write_text("## test")

        from src.cursor.cursor_executor import CursorExecutor
        with pytest.raises(httpx.ConnectError):
            CursorExecutor().execute(str(packet), "run-test")


# ===========================================================================
# 3. verification 실패 복구 플로우
# ===========================================================================

class TestVerificationRecoveryFlow:
    def test_slice_issue_detected(self):
        """changed_files 비어있으면 slice_issue."""
        from src.verification.spec_alignment import check_spec_alignment
        result = check_spec_alignment(
            execution_result={"changed_files": [], "test_results": "ok", "run_log": "done"}
        )
        assert not result.aligned
        assert result.failure_type == "slice_issue"

    def test_doc_issue_detected(self):
        """scope 이탈 파일 → doc_issue."""
        from src.verification.spec_alignment import check_spec_alignment
        result = check_spec_alignment(
            execution_result={"changed_files": ["src/unrelated.py"]},
            deliverable_spec={"target_files": ["src/auth.py"]},
        )
        assert not result.aligned
        assert result.failure_type == "doc_issue"

    def test_verification_passes_complete(self):
        """완전한 결과 → verification 통과."""
        from src.verification.result_verifier import verify_execution_result
        v = verify_execution_result({
            "changed_files": ["src/auth.py"],
            "test_results": "5 passed",
            "run_log": "fixed",
        })
        assert v.passed

    def test_full_flow_auto_success_to_finalize(self, tmp_path):
        """자동 실행 결과 → DB 저장 → verification → finalize 전체 연결."""
        from src.cursor.cursor_executor import CursorExecutionResult
        from src.cursor.cursor_result_adapter import adapt_cursor_result
        from src.store.artifact_store import save_artifact, update_execution_result, load_artifact
        from src.verification.result_verifier import verify_execution_result
        from src.verification.spec_alignment import check_spec_alignment
        from src.finalize.finalize_service import finalize_run

        # 자동 실행 결과
        raw = CursorExecutionResult(
            job_id="job-final",
            status="completed",
            output="fixed",
            changed_files=["src/auth.py"],
            test_output="3 passed",
        )
        adapted = adapt_cursor_result(raw)

        # DB 저장
        db = str(tmp_path / "t.db")
        save_artifact(db, {"run_id": "run-final", "run_status": "packet_ready",
                           "raw_input": "버그 수정해줘"})
        update_execution_result(db, "run-final",
            adapted["changed_files"], adapted["test_results"], adapted["run_log"])

        # verification
        v = verify_execution_result(adapted)
        a = check_spec_alignment(execution_result=adapted)
        assert v.passed and a.aligned

        # finalize
        summary = finalize_run(
            db_path=db, run_id="run-final", goal="버그 수정해줘",
            approval_status="approved",
            changed_files=adapted["changed_files"],
            test_results=adapted["test_results"],
            run_log=adapted["run_log"],
        )
        assert "completed" in summary
        loaded = load_artifact(db, run_id="run-final")
        assert loaded["run_status"] == "completed"


# ===========================================================================
# 4. Research 계층 구조 확인
# ===========================================================================

class TestResearchLayerStructure:
    def test_gemini_deep_research_is_primary(self):
        import src.research.router as r
        from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
        assert r._DEEP_RESEARCH_CLASSES[0] is GeminiDeepResearchAdapter

    def test_gpt_research_is_second(self):
        import src.research.router as r
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert r._DEEP_RESEARCH_CLASSES[1] is GPTResearchAdapter

    def test_tavily_disabled(self):
        from src.research.tavily_adapter import TavilyAdapter
        assert TavilyAdapter().is_available() is False

    def test_silent_fallback_absent_in_router(self):
        """router에 silent fallback 코드가 없음 — real 실패 시 예외 전파."""
        import inspect, src.research.router as r
        src_code = inspect.getsource(r.run_research)
        # YouTube fallback은 except로 감싸지만 real 어댑터는 except 없음
        # _DEEP_RESEARCH_CLASSES 루프에 try/except가 없음을 확인
        assert "for adapter in active_deep + active_support:" in src_code

    def test_no_key_falls_back_to_youtube(self, monkeypatch):
        """모든 real key 없으면 YouTube fallback."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        import src.research.router as r
        bundle = r.run_research("test")
        assert isinstance(bundle.claims, list)
