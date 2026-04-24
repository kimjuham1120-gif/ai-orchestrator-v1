"""
Day 120 — Phase 4 · AI 교차 감사 테스트.

검증 포인트:
1. CrossAuditResult 구조
2. ON/OFF 게이트 (PHASE_4_ENABLED)
3. 입력 검증 (target_doc 유효성)
4. 정상 경로 (3감사 + 통합 전부 성공)
5. 부분 실패 (일부 감사만 성공 → 통합 진행)
6. 모든 감사 실패
7. 감사 성공하나 통합 실패
8. base_info_doc 참조 전달
9. 병렬 실행 확인
10. 모델 선택 환경변수
"""
from __future__ import annotations

import threading
import time
import pytest
from unittest.mock import patch, MagicMock

from src.phases.phase_4_audit import (
    run_cross_audit, CrossAuditResult,
    STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED,
    AUDITOR_STRUCTURE, AUDITOR_BALANCE, AUDITOR_FACT,
)


# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------

_PATCH = "src.utils.llm_utils.httpx"   # 모든 테스트에서 이 경로로 패치


def _mock_ok(text="응답"):
    m = MagicMock()
    m.status_code = 200
    m.raise_for_status = MagicMock()
    m.json.return_value = {"choices": [{"message": {"content": text}}]}
    return m


def _mock_err(status=500):
    m = MagicMock()
    m.status_code = status
    m.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return m


def _sample_target_doc(text="# 목표 문서\n본문 내용 3개 섹션"):
    return {"document": text, "created_at": "2026-04-21T09:00:00+00:00"}


def _sample_base_info_doc(text="# 기반정보\n사실 근거 자료"):
    return {"document": text, "created_at": "2026-04-21T08:00:00+00:00"}


def _get_text(kwargs):
    """캐싱 형식(list) 또는 일반 형식(str) 모두 처리."""
    msg = kwargs["json"]["messages"][0]["content"]
    if isinstance(msg, list):
        return msg[0].get("text", "")
    return msg


# ===========================================================================
# 1. 결과 타입 구조
# ===========================================================================

class TestResultStructure:
    def test_to_dict_has_all_keys(self):
        r = CrossAuditResult()
        d = r.to_dict()
        for key in ["enabled", "round", "audits", "synthesized_doc",
                    "original_doc", "status", "error"]:
            assert key in d

    def test_defaults(self):
        r = CrossAuditResult()
        assert r.enabled is True
        assert r.round == 1
        assert r.audits == {}
        assert r.synthesized_doc is None
        assert r.status == STATUS_SKIPPED

    def test_successful_auditors_count(self):
        r = CrossAuditResult(audits={
            "structure": {"status": STATUS_SUCCESS},
            "balance":   {"status": STATUS_FAILED},
            "fact":      {"status": STATUS_SUCCESS},
        })
        assert r.successful_auditors == 2

    def test_is_success_requires_doc_and_status(self):
        r1 = CrossAuditResult(status=STATUS_SUCCESS)
        assert r1.is_success is False

        r2 = CrossAuditResult(
            status=STATUS_SUCCESS,
            synthesized_doc={"document": "x", "created_at": "y"},
        )
        assert r2.is_success is True


# ===========================================================================
# 2. ON/OFF 게이트
# ===========================================================================

class TestEnableGate:
    def test_disabled_returns_skipped(self, monkeypatch):
        monkeypatch.setenv("PHASE_4_ENABLED", "false")
        r = run_cross_audit(_sample_target_doc(), "요청")
        assert r.enabled is False
        assert r.status == STATUS_SKIPPED
        assert r.synthesized_doc is None
        assert r.original_doc == _sample_target_doc()

    def test_disabled_no_llm_calls(self, monkeypatch):
        monkeypatch.setenv("PHASE_4_ENABLED", "false")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_PATCH) as mhttpx:
            run_cross_audit(_sample_target_doc(), "요청")
            assert not mhttpx.post.called

    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("PHASE_4_ENABLED", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        r = run_cross_audit(_sample_target_doc(), "요청")
        assert r.enabled is True
        assert r.status == STATUS_FAILED  # API 키 없어서 실패

    def test_case_insensitive_false(self, monkeypatch):
        for val in ["FALSE", "False", "false", "fAlSe"]:
            monkeypatch.setenv("PHASE_4_ENABLED", val)
            r = run_cross_audit(_sample_target_doc(), "요청")
            assert r.status == STATUS_SKIPPED


# ===========================================================================
# 3. 입력 검증
# ===========================================================================

class TestInputValidation:
    def test_non_dict_target_fails(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        r = run_cross_audit("not a dict", "요청")
        assert r.status == STATUS_FAILED
        assert "dict" in r.error

    def test_empty_document_fails(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        r = run_cross_audit({"document": ""}, "요청")
        assert r.status == STATUS_FAILED

    def test_whitespace_document_fails(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        r = run_cross_audit({"document": "   \n\t   "}, "요청")
        assert r.status == STATUS_FAILED


# ===========================================================================
# 4. 정상 경로 (전부 성공)
# ===========================================================================

class TestHappyPath:
    def test_all_three_auditors_plus_synthesizer(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        def side_effect(*args, **kwargs):
            text = _get_text(kwargs)
            if "**구조 감사관**" in text: return _mock_ok("구조 감사 피드백")
            if "**균형 감사관**" in text: return _mock_ok("균형 감사 피드백")
            if "**사실 감사관**" in text: return _mock_ok("사실 감사 피드백")
            if "**편집자**" in text:      return _mock_ok("# 고도화 문서\n개선된 본문")
            return _mock_ok("default")

        with patch(_PATCH) as mhttpx:
            mhttpx.post.side_effect = side_effect
            r = run_cross_audit(_sample_target_doc(), "요청")

        assert r.status == STATUS_SUCCESS
        assert r.is_success is True
        assert r.successful_auditors == 3
        assert r.audits[AUDITOR_STRUCTURE]["status"] == STATUS_SUCCESS
        assert r.audits[AUDITOR_BALANCE]["status"] == STATUS_SUCCESS
        assert r.audits[AUDITOR_FACT]["status"] == STATUS_SUCCESS
        assert r.synthesized_doc is not None
        assert "고도화 문서" in r.synthesized_doc["document"]
        assert r.synthesized_doc["created_at"]

    def test_audits_contain_model_info(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_PATCH) as mhttpx:
            mhttpx.post.return_value = _mock_ok("피드백")
            r = run_cross_audit(_sample_target_doc(), "요청")

        for name in [AUDITOR_STRUCTURE, AUDITOR_BALANCE, AUDITOR_FACT]:
            assert "model" in r.audits[name]
            assert r.audits[name]["model"]

    def test_original_doc_preserved(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        target = _sample_target_doc()
        with patch(_PATCH) as mhttpx:
            mhttpx.post.return_value = _mock_ok("x")
            r = run_cross_audit(target, "요청")
        assert r.original_doc == target


# ===========================================================================
# 5. 부분 실패 (partial)
# ===========================================================================

class TestPartialFailure:
    def test_one_auditor_fails_synthesis_proceeds(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        def side_effect(*args, **kwargs):
            import httpx as _httpx
            model = kwargs["json"]["model"]
            text = _get_text(kwargs)
            if "gemini" in model:
                raise _httpx.ConnectError("gemini down")
            if "**구조 감사관**" in text: return _mock_ok("구조 피드백")
            if "**균형 감사관**" in text: return _mock_ok("균형 피드백")
            if "**편집자**" in text:      return _mock_ok("# 통합 문서")
            return _mock_ok("x")

        with patch(_PATCH) as mhttpx:
            mhttpx.post.side_effect = side_effect
            mhttpx.ConnectError = __import__("httpx").ConnectError
            r = run_cross_audit(_sample_target_doc(), "요청")

        assert r.status == STATUS_SUCCESS
        assert r.successful_auditors == 2
        assert r.audits[AUDITOR_FACT]["status"] == STATUS_FAILED
        assert r.synthesized_doc is not None

    def test_two_auditors_fail_synthesis_still_proceeds(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx as _httpx

        def side_effect(*args, **kwargs):
            model = kwargs["json"]["model"]
            text = _get_text(kwargs)
            if "claude-opus" in model:  raise _httpx.ConnectError("claude-opus down")
            if "gemini" in model:  raise _httpx.ConnectError("gemini down")
            if "**균형 감사관**" in text: return _mock_ok("균형 피드백")
            if "**편집자**" in text:      return _mock_ok("# 통합 문서")
            return _mock_ok("x")

        with patch(_PATCH) as mhttpx:
            mhttpx.post.side_effect = side_effect
            mhttpx.ConnectError = _httpx.ConnectError
            r = run_cross_audit(_sample_target_doc(), "요청")

        assert r.status == STATUS_SUCCESS
        assert r.successful_auditors == 1


# ===========================================================================
# 6. 모든 감사관 실패
# ===========================================================================

class TestAllAuditorsFail:
    def test_all_auditors_fail_returns_failed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx as _httpx

        with patch(_PATCH) as mhttpx:
            mhttpx.post.side_effect = _httpx.ConnectError("all down")
            mhttpx.ConnectError = _httpx.ConnectError
            r = run_cross_audit(_sample_target_doc(), "요청")

        assert r.status == STATUS_FAILED
        assert r.successful_auditors == 0
        assert r.synthesized_doc is None
        assert r.error is not None

    def test_all_empty_responses_fail(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_PATCH) as mhttpx:
            mhttpx.post.return_value = _mock_ok("")
            r = run_cross_audit(_sample_target_doc(), "요청")
        assert r.status == STATUS_FAILED


# ===========================================================================
# 7. 감사는 성공, 통합만 실패
# ===========================================================================

class TestSynthesizerFailure:
    def test_synth_fails_audits_preserved(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx as _httpx

        def side_effect(*args, **kwargs):
            text = _get_text(kwargs)
            if "**구조 감사관**" in text: return _mock_ok("구조 피드백")
            if "**균형 감사관**" in text: return _mock_ok("균형 피드백")
            if "**사실 감사관**" in text: return _mock_ok("사실 피드백")
            if "**편집자**" in text:      raise _httpx.ConnectError("synth down")
            return _mock_ok("x")

        with patch(_PATCH) as mhttpx:
            mhttpx.post.side_effect = side_effect
            mhttpx.ConnectError = _httpx.ConnectError
            r = run_cross_audit(_sample_target_doc(), "요청")

        assert r.status == STATUS_FAILED
        assert r.synthesized_doc is None
        assert r.successful_auditors == 3
        for a in r.audits.values():
            assert a["status"] == STATUS_SUCCESS
        assert "통합" in r.error


# ===========================================================================
# 8. base_info_doc 참조 전달
# ===========================================================================

class TestBaseInfoReference:
    def test_base_info_in_fact_auditor_prompt(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        captured = []
        def capture(*args, **kwargs):
            captured.append((kwargs["json"]["model"], _get_text(kwargs)))
            return _mock_ok("피드백")

        with patch(_PATCH) as mhttpx:
            mhttpx.post.side_effect = capture
            run_cross_audit(
                _sample_target_doc(),
                "요청",
                base_info_doc=_sample_base_info_doc("특별한_기반정보_마커"),
            )

        fact_calls = [(m, t) for m, t in captured if "gemini" in m]
        assert len(fact_calls) >= 1
        assert "특별한_기반정보_마커" in fact_calls[0][1]

    def test_no_base_info_works(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_PATCH) as mhttpx:
            mhttpx.post.return_value = _mock_ok("x")
            r = run_cross_audit(_sample_target_doc(), "요청", base_info_doc=None)
        assert r.enabled is True

    def test_base_info_included_in_synthesizer(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        captured = []
        def capture(*args, **kwargs):
            captured.append(_get_text(kwargs))
            return _mock_ok("x")

        with patch(_PATCH) as mhttpx:
            mhttpx.post.side_effect = capture
            run_cross_audit(
                _sample_target_doc(),
                "요청",
                base_info_doc=_sample_base_info_doc("기반마커XYZ"),
            )

        synth_prompts = [c for c in captured if "편집자" in c]
        assert len(synth_prompts) >= 1
        assert "기반마커XYZ" in synth_prompts[0]


# ===========================================================================
# 9. 병렬 실행 확인
# ===========================================================================

class TestParallelExecution:
    def test_auditors_run_in_parallel(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        thread_ids = set()
        lock = threading.Lock()

        def tracked(*args, **kwargs):
            text = _get_text(kwargs)
            if "감사관**입니다" in text:
                with lock:
                    thread_ids.add(threading.get_ident())
                time.sleep(0.05)
            return _mock_ok("피드백")

        with patch(_PATCH) as mhttpx:
            mhttpx.post.side_effect = tracked
            run_cross_audit(_sample_target_doc(), "요청")

        assert len(thread_ids) >= 2, f"감사관이 모두 같은 스레드 (thread_ids={thread_ids})"


# ===========================================================================
# 10. 모델 선택 환경변수
# ===========================================================================

class TestModelSelection:
    def test_default_models_match_scope(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        for var in ["AUDITOR_STRUCTURE_MODEL", "AUDITOR_BALANCE_MODEL",
                    "AUDITOR_FACT_MODEL", "AUDITOR_SYNTHESIZER_MODEL"]:
            monkeypatch.delenv(var, raising=False)

        captured_models = []
        def capture(*args, **kwargs):
            captured_models.append(kwargs["json"]["model"])
            return _mock_ok("x")

        with patch(_PATCH) as mhttpx:
            mhttpx.post.side_effect = capture
            run_cross_audit(_sample_target_doc(), "요청")

        assert any("claude-opus-4.7" in m for m in captured_models)
        assert any("gemini-3.1-pro" in m for m in captured_models)
        # 균형 감사관 (GPT-5.4)
        assert any("gpt-5.4" in m for m in captured_models)
        # 통합 LLM (Step 14-2: Sonnet 4.6으로 전환됨)
        assert any("claude-sonnet-4-6" in m for m in captured_models)

    def test_custom_structure_model(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("AUDITOR_STRUCTURE_MODEL", "custom/my-claude")

        captured = []
        def capture(*args, **kwargs):
            captured.append(kwargs["json"]["model"])
            return _mock_ok("x")

        with patch(_PATCH) as mhttpx:
            mhttpx.post.side_effect = capture
            run_cross_audit(_sample_target_doc(), "요청")

        assert "custom/my-claude" in captured


# ===========================================================================
# 11. 스모크
# ===========================================================================

class TestSmoke:
    def test_always_returns_cross_audit_result(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        cases = [
            (_sample_target_doc(), "요청", None),
            (_sample_target_doc(), "", _sample_base_info_doc()),
            (None, "요청", None),
            ({}, "요청", None),
            ({"document": ""}, "요청", None),
        ]
        for target, raw, base in cases:
            r = run_cross_audit(target, raw, base_info_doc=base)
            assert isinstance(r, CrossAuditResult)
