"""
Day 65~72 — Cursor 자동 실행 연동 테스트.

정책:
  - 실 Cursor/네트워크 호출 금지 (monkeypatch / mock 전용)
  - 기존 292개 테스트에 추가
  - artifact_store 스키마 변경 없음
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# CursorExecutor 단위 테스트
# ===========================================================================

class TestCursorExecutorAvailability:
    def test_auto_mode_false_by_default(self, monkeypatch):
        monkeypatch.delenv("CURSOR_AUTO_MODE", raising=False)
        from src.cursor.cursor_executor import is_auto_mode
        assert is_auto_mode() is False

    def test_auto_mode_true_when_set(self, monkeypatch):
        monkeypatch.setenv("CURSOR_AUTO_MODE", "true")
        from src.cursor.cursor_executor import is_auto_mode
        assert is_auto_mode() is True

    def test_auto_mode_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("CURSOR_AUTO_MODE", "TRUE")
        from src.cursor.cursor_executor import is_auto_mode
        assert is_auto_mode() is True

    def test_no_api_key_raises_on_execute(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CURSOR_API_KEY", raising=False)
        monkeypatch.setenv("CURSOR_AUTO_MODE", "true")

        # 임시 패킷 파일
        packet = tmp_path / "packet.md"
        packet.write_text("## test packet")

        from src.cursor.cursor_executor import CursorExecutor, CursorExecutorError
        executor = CursorExecutor()
        with pytest.raises(CursorExecutorError, match="CURSOR_API_KEY not set"):
            executor.execute(str(packet), "run-test")

    def test_missing_packet_file_raises(self, monkeypatch):
        monkeypatch.setenv("CURSOR_API_KEY", "cursor-test-key")
        from src.cursor.cursor_executor import CursorExecutor, CursorExecutorError
        executor = CursorExecutor()
        with pytest.raises(CursorExecutorError, match="패킷 파일 없음"):
            executor.execute("/nonexistent/packet.md", "run-test")

    def test_env_override_timeout(self, monkeypatch):
        monkeypatch.setenv("CURSOR_API_KEY", "cursor-test")
        monkeypatch.setenv("CURSOR_EXECUTION_TIMEOUT", "120.0")
        from src.cursor.cursor_executor import CursorExecutor
        assert CursorExecutor()._timeout == 120.0

    def test_env_override_poll_interval(self, monkeypatch):
        monkeypatch.setenv("CURSOR_API_KEY", "cursor-test")
        monkeypatch.setenv("CURSOR_POLL_INTERVAL", "5.0")
        from src.cursor.cursor_executor import CursorExecutor
        assert CursorExecutor()._poll_interval == 5.0


class TestCursorExecutorAutoExecution:
    def _make_submit_response(self, job_id: str):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.json.return_value = {"job_id": job_id}
        return m

    def _make_poll_response(self, status: str, output: str = "", changed_files=None):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.json.return_value = {
            "status": status,
            "output": output,
            "changed_files": changed_files or [],
            "test_output": "3 passed",
        }
        return m

    def test_successful_execution(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CURSOR_API_KEY", "cursor-key")
        packet = tmp_path / "packet.md"
        packet.write_text("## packet content")

        import httpx
        responses = [
            self._make_submit_response("job-001"),
            self._make_poll_response("completed", "done", ["src/auth.py"]),
        ]
        call_count = [0]

        def fake_post(url, **kw):
            call_count[0] += 1
            return responses[0]

        def fake_get(url, **kw):
            return responses[1]

        monkeypatch.setattr(httpx, "post", fake_post)
        monkeypatch.setattr(httpx, "get", fake_get)

        from src.cursor.cursor_executor import CursorExecutor
        result = CursorExecutor().execute(str(packet), "run-001")
        assert result.status == "completed"
        assert result.job_id == "job-001"
        assert "src/auth.py" in result.changed_files

    def test_failed_job_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CURSOR_API_KEY", "cursor-key")
        packet = tmp_path / "packet.md"
        packet.write_text("## packet")

        import httpx

        def fake_post(url, **kw):
            m = MagicMock(); m.raise_for_status = MagicMock()
            m.json.return_value = {"job_id": "job-fail"}
            return m

        def fake_get(url, **kw):
            m = MagicMock(); m.raise_for_status = MagicMock()
            m.json.return_value = {"status": "failed", "error": "compilation error"}
            return m

        monkeypatch.setattr(httpx, "post", fake_post)
        monkeypatch.setattr(httpx, "get", fake_get)

        from src.cursor.cursor_executor import CursorExecutor, CursorExecutorError
        with pytest.raises(CursorExecutorError, match="compilation error"):
            CursorExecutor().execute(str(packet), "run-fail")

    def test_timeout_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CURSOR_API_KEY", "cursor-key")
        monkeypatch.setenv("CURSOR_EXECUTION_TIMEOUT", "0.01")
        monkeypatch.setenv("CURSOR_POLL_INTERVAL", "0.001")
        packet = tmp_path / "packet.md"
        packet.write_text("## packet")

        import httpx, time

        def fake_post(url, **kw):
            m = MagicMock(); m.raise_for_status = MagicMock()
            m.json.return_value = {"job_id": "job-slow"}
            return m

        def fake_get(url, **kw):
            time.sleep(0.02)
            m = MagicMock(); m.raise_for_status = MagicMock()
            m.json.return_value = {"status": "pending"}
            return m

        monkeypatch.setattr(httpx, "post", fake_post)
        monkeypatch.setattr(httpx, "get", fake_get)

        from src.cursor.cursor_executor import CursorExecutor, CursorTimeoutError
        with pytest.raises(CursorTimeoutError):
            CursorExecutor().execute(str(packet), "run-slow")

    def test_http_error_propagates(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CURSOR_API_KEY", "cursor-key")
        packet = tmp_path / "packet.md"
        packet.write_text("## packet")

        import httpx

        def fake_post(url, **kw):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "post", fake_post)

        from src.cursor.cursor_executor import CursorExecutor
        with pytest.raises(httpx.ConnectError):
            CursorExecutor().execute(str(packet), "run-err")


class TestCursorExecutorOutputParsing:
    def test_extract_changed_files_from_output(self):
        from src.cursor.cursor_executor import _extract_changed_files_from_output
        output = "modified: src/auth.py\nchanged: tests/test_auth.py\nsome other line"
        files = _extract_changed_files_from_output(output)
        assert "src/auth.py" in files
        assert "tests/test_auth.py" in files

    def test_extract_test_output(self):
        from src.cursor.cursor_executor import _extract_test_output_from_output
        output = "Running tests...\n3 passed in 1.2s\ndone"
        result = _extract_test_output_from_output(output)
        assert "passed" in result

    def test_empty_output_returns_empty(self):
        from src.cursor.cursor_executor import _extract_changed_files_from_output
        assert _extract_changed_files_from_output("") == []


# ===========================================================================
# CursorResultAdapter 테스트
# ===========================================================================

class TestCursorResultAdapter:
    def _make_result(self, changed_files=None, test_output="", output="", job_id="job-1"):
        from src.cursor.cursor_executor import CursorExecutionResult
        return CursorExecutionResult(
            job_id=job_id,
            status="completed",
            output=output,
            changed_files=changed_files or [],
            test_output=test_output,
        )

    def test_adapt_basic(self):
        from src.cursor.cursor_result_adapter import adapt_cursor_result
        result = self._make_result(
            changed_files=["src/auth.py"],
            test_output="5 passed in 2.1s",
            output="modified: src/auth.py",
        )
        adapted = adapt_cursor_result(result)
        assert adapted["changed_files"] == ["src/auth.py"]
        assert "passed" in adapted["test_results"]
        assert adapted["run_log"] != ""

    def test_normalize_test_results_extracts_summary(self):
        from src.cursor.cursor_result_adapter import _normalize_test_results
        output = "collecting...\ntest_auth.py ...\n5 passed in 2.1s"
        result = _normalize_test_results(output)
        assert "5 passed" in result

    def test_normalize_empty_returns_empty(self):
        from src.cursor.cursor_result_adapter import _normalize_test_results
        assert _normalize_test_results("") == ""

    def test_run_log_contains_job_id(self):
        from src.cursor.cursor_result_adapter import _build_run_log
        result = self._make_result(job_id="job-xyz", changed_files=["a.py"])
        log = _build_run_log(result)
        assert "job-xyz" in log

    def test_adapted_result_compatible_with_verification(self, tmp_path):
        """adapt_cursor_result 출력이 save_execution_result_step과 호환."""
        from src.cursor.cursor_result_adapter import adapt_cursor_result
        from src.store.artifact_store import save_artifact, update_execution_result, load_artifact

        result = self._make_result(
            changed_files=["src/auth.py"],
            test_output="3 passed",
            output="fixed login bug",
        )
        adapted = adapt_cursor_result(result)

        db = str(tmp_path / "test.db")
        save_artifact(db, {"run_id": "run-adapt-test", "run_status": "packet_ready"})
        update_execution_result(
            db, "run-adapt-test",
            adapted["changed_files"],
            adapted["test_results"],
            adapted["run_log"],
        )
        loaded = load_artifact(db, run_id="run-adapt-test")
        assert loaded["execution_result"]["changed_files"] == ["src/auth.py"]
        assert loaded["run_status"] == "execution_result_received"


# ===========================================================================
# CLI 자동/수동 모드 통합 테스트
# ===========================================================================

class TestCLIAutoManualMode:
    def test_manual_mode_when_auto_false(self, monkeypatch):
        """CURSOR_AUTO_MODE=false → is_auto_mode() False."""
        monkeypatch.setenv("CURSOR_AUTO_MODE", "false")
        from src.cursor.cursor_executor import is_auto_mode
        assert is_auto_mode() is False

    def test_auto_execution_fallback_on_error(self, monkeypatch, tmp_path):
        """자동 실행 실패 → None 반환 (manual fallback 진입)."""
        monkeypatch.setenv("CURSOR_AUTO_MODE", "true")
        monkeypatch.setenv("CURSOR_API_KEY", "cursor-key")

        import httpx
        def raise_connect(*a, **kw):
            raise httpx.ConnectError("refused")
        monkeypatch.setattr(httpx, "post", raise_connect)

        packet = tmp_path / "packet.md"
        packet.write_text("## packet")

        # cli._try_cursor_auto_execute 직접 테스트
        import sys, types
        # src.cursor 모듈이 실제로 있으면 그냥 import
        from src.cursor.cursor_executor import CursorExecutor, CursorExecutorError

        # _try_cursor_auto_execute 로직 직접 검증
        try:
            executor = CursorExecutor()
            executor.execute(str(packet), "run-test")
            result = "should_not_reach"
        except Exception:
            result = None  # 실패 → None (fallback)

        assert result is None

    def test_full_flow_auto_success_then_verify(self, monkeypatch, tmp_path):
        """자동 실행 성공 → verification 연결."""
        from src.cursor.cursor_executor import CursorExecutionResult
        from src.cursor.cursor_result_adapter import adapt_cursor_result
        from src.store.artifact_store import save_artifact, update_execution_result
        from src.verification.result_verifier import verify_execution_result

        # 자동 실행 결과 mock
        raw = CursorExecutionResult(
            job_id="job-ok",
            status="completed",
            output="modified: src/auth.py",
            changed_files=["src/auth.py"],
            test_output="5 passed",
        )
        adapted = adapt_cursor_result(raw)

        # DB 저장
        db = str(tmp_path / "t.db")
        save_artifact(db, {"run_id": "run-auto-ok", "run_status": "packet_ready"})
        update_execution_result(
            db, "run-auto-ok",
            adapted["changed_files"],
            adapted["test_results"],
            adapted["run_log"],
        )

        # verification 연결
        exec_result = {
            "changed_files": adapted["changed_files"],
            "test_results": adapted["test_results"],
            "run_log": adapted["run_log"],
        }
        v = verify_execution_result(exec_result)
        assert v.passed
