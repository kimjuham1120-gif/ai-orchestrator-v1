"""
Day 119 — Phase 5 · 사용자 검수 루프 테스트.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.phases.phase_5_feedback import (
    apply_feedback, append_version, confirm_final, get_recent_versions,
    FeedbackResult, ConfirmResult, STATUS_SUCCESS, STATUS_FAILED,
)

_PATCH = "src.utils.llm_utils.httpx.post"


def _mock_ok(text="응답"):
    m = MagicMock()
    m.status_code = 200
    m.raise_for_status = MagicMock()
    m.json.return_value = {"choices": [{"message": {"content": text}}]}
    return m


def _sample_doc(text="# 원본 문서\n핵심 내용"):
    return {"document": text, "created_at": "2026-04-21T09:00:00+00:00"}


# ===========================================================================
# 1. 결과 타입 구조
# ===========================================================================

class TestResultTypes:
    def test_feedback_result_to_dict(self):
        r = FeedbackResult(status=STATUS_SUCCESS)
        d = r.to_dict()
        for key in ["status", "new_doc", "error", "feedback_applied"]:
            assert key in d

    def test_feedback_is_success_property(self):
        assert FeedbackResult(status=STATUS_SUCCESS, new_doc=_sample_doc()).is_success is True
        assert FeedbackResult(status=STATUS_SUCCESS, new_doc=None).is_success is False
        assert FeedbackResult(status=STATUS_FAILED).is_success is False

    def test_confirm_result_to_dict(self):
        r = ConfirmResult(confirmed=True)
        d = r.to_dict()
        for key in ["confirmed", "final_doc", "confirmed_at", "error"]:
            assert key in d


# ===========================================================================
# 2. apply_feedback — 입력 검증
# ===========================================================================

class TestApplyFeedbackValidation:
    def test_empty_current_doc_fails(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        r = apply_feedback({}, "피드백", "요청")
        assert r.status == STATUS_FAILED
        assert "current_doc" in r.error

    def test_current_doc_without_document_key_fails(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        r = apply_feedback({"other": "x"}, "피드백")
        assert r.status == "failed"

    def test_empty_document_fails(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        r = apply_feedback({"document": ""}, "피드백")
        assert r.status == "failed"

    def test_whitespace_document_fails(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        r = apply_feedback({"document": "   \n"}, "피드백")
        assert r.status == "failed"

    def test_empty_feedback_fails(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        r = apply_feedback(_sample_doc(), "")
        assert r.status == "failed"

    def test_whitespace_feedback_fails(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        r = apply_feedback(_sample_doc(), "   ")
        assert r.status == "failed"


# ===========================================================================
# 3. apply_feedback — LLM 경로
# ===========================================================================

class TestApplyFeedbackLLM:
    def test_successful_llm_returns_new_doc(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_PATCH, return_value=_mock_ok("개선된 문서")):
            r = apply_feedback(_sample_doc(), "재무 계획 보강", raw_input="사업계획서 써줘")
        assert r.status == STATUS_SUCCESS
        assert r.new_doc["document"] == "개선된 문서"
        assert r.feedback_applied == "재무 계획 보강"
        assert r.error is None

    def test_no_api_key_returns_failed(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        r = apply_feedback(_sample_doc(), "피드백")
        assert r.status == "failed"

    def test_network_error_returns_failed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx
        with patch(_PATCH, side_effect=httpx.ConnectError("down")):
            r = apply_feedback(_sample_doc(), "피드백")
        assert r.status == "failed"
        assert r.new_doc is None

    def test_empty_llm_response_returns_failed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_PATCH, return_value=_mock_ok("")):
            r = apply_feedback(_sample_doc(), "피드백")
        assert r.status == "failed"

    def test_markdown_wrapper_stripped(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_PATCH, return_value=_mock_ok("```markdown\n# 문서\n내용\n```")):
            r = apply_feedback(_sample_doc(), "피드백")
        assert r.status == "success"
        assert not r.new_doc["document"].startswith("```")
        assert "# 문서" in r.new_doc["document"]


# ===========================================================================
# 4. apply_feedback — base_info_doc 포함
# ===========================================================================

class TestApplyFeedbackBaseInfo:
    def test_base_info_included_in_prompt(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        base_info = {"document": "특별한_기반정보_텍스트", "created_at": "x"}
        captured = []
        def capture(*args, **kwargs):
            msg = kwargs["json"]["messages"][0]["content"]
            captured.append(msg[0]["text"] if isinstance(msg, list) else msg)
            return _mock_ok("개선본")
        with patch(_PATCH, side_effect=capture):
            apply_feedback(_sample_doc(), "피드백", raw_input="요청", base_info_doc=base_info)
        assert "특별한_기반정보_텍스트" in captured[0]

    def test_base_info_none_no_error(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_PATCH, return_value=_mock_ok("개선본")):
            r = apply_feedback(_sample_doc(), "피드백", base_info_doc=None)
        assert r.status == "success"

    def test_base_info_empty_document_ignored(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_PATCH, return_value=_mock_ok("개선본")):
            r = apply_feedback(_sample_doc(), "피드백", base_info_doc={"document": ""})
        assert r.status == "success"


# ===========================================================================
# 5. append_version
# ===========================================================================

class TestAppendVersion:
    def test_first_version_starts_at_1(self):
        versions = append_version(None, _sample_doc("v1 본문"))
        assert versions[0]["version"] == 1
        assert versions[0]["feedback_applied"] is None

    def test_empty_list_starts_at_1(self):
        assert append_version([], _sample_doc("v1"))[0]["version"] == 1

    def test_second_version_is_2(self):
        v1 = append_version(None, _sample_doc("v1"))
        v2 = append_version(v1, _sample_doc("v2"), feedback_applied="재무 보강")
        assert v2[1]["version"] == 2
        assert v2[1]["feedback_applied"] == "재무 보강"

    def test_multiple_versions_increment(self):
        versions = None
        for i in range(5):
            versions = append_version(versions, _sample_doc(f"v{i+1}"))
        assert [v["version"] for v in versions] == [1, 2, 3, 4, 5]

    def test_original_list_not_mutated(self):
        original = append_version(None, _sample_doc("v1"))
        new_versions = append_version(original, _sample_doc("v2"))
        assert len(original) == 1
        assert len(new_versions) == 2

    def test_invalid_new_doc_raises(self):
        with pytest.raises(ValueError):
            append_version(None, {})

    def test_invalid_new_doc_empty_document_raises(self):
        with pytest.raises(ValueError):
            append_version(None, {"document": ""})

    def test_version_preserves_all_required_fields(self):
        entry = append_version(None, _sample_doc("본문"), feedback_applied="피드백")[0]
        for key in ["version", "document", "feedback_applied", "created_at"]:
            assert key in entry

    def test_created_at_used_from_new_doc(self):
        doc = {"document": "본문", "created_at": "2026-04-21T12:34:56+00:00"}
        assert append_version(None, doc)[0]["created_at"] == "2026-04-21T12:34:56+00:00"

    def test_handles_malformed_existing_versions(self):
        bad = [{"version": 1}, "bad", {"no_version": True}, {"version": 3}]
        assert append_version(bad, _sample_doc("v4"))[-1]["version"] == 4


# ===========================================================================
# 6. confirm_final
# ===========================================================================

class TestConfirmFinal:
    def test_valid_doc_confirmed(self):
        r = confirm_final(_sample_doc("최종본"))
        assert r.confirmed is True
        assert r.confirmed_at is not None

    def test_empty_doc_not_confirmed(self):
        assert confirm_final({}).confirmed is False

    def test_none_not_confirmed(self):
        assert confirm_final(None).confirmed is False

    def test_empty_document_not_confirmed(self):
        assert confirm_final({"document": ""}).confirmed is False

    def test_whitespace_document_not_confirmed(self):
        assert confirm_final({"document": "   \t\n"}).confirmed is False


# ===========================================================================
# 7. get_recent_versions
# ===========================================================================

class TestGetRecentVersions:
    def _make(self, n):
        v = None
        for i in range(n):
            v = append_version(v, _sample_doc(f"v{i+1}"))
        return v

    def test_returns_empty_for_none(self):
        assert get_recent_versions(None) == []

    def test_returns_empty_for_empty(self):
        assert get_recent_versions([]) == []

    def test_default_limit_10(self):
        assert len(get_recent_versions(self._make(15))) == 10

    def test_custom_limit(self):
        assert len(get_recent_versions(self._make(20), limit=5)) == 5

    def test_returns_all_if_under_limit(self):
        assert len(get_recent_versions(self._make(3), limit=10)) == 3

    def test_sorted_by_version_desc(self):
        recent = get_recent_versions(self._make(5), limit=3)
        assert [r["version"] for r in recent] == [5, 4, 3]

    def test_zero_limit_returns_empty(self):
        assert get_recent_versions(self._make(5), limit=0) == []

    def test_negative_limit_returns_empty(self):
        assert get_recent_versions(self._make(5), limit=-1) == []


# ===========================================================================
# 8. 전체 사이클 스모크
# ===========================================================================

class TestFullCycleSmoke:
    def test_three_feedback_rounds_then_confirm(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        responses = [_mock_ok(f"# 문서 v{i}\n개선{i}") for i in range(2, 5)]
        idx = [0]
        def seq(*a, **kw):
            r = responses[idx[0]]; idx[0] += 1; return r

        with patch(_PATCH, side_effect=seq):
            current = _sample_doc("# 문서 v1\n초안")
            versions = append_version(None, current)
            for fb in ["재무 강화", "경쟁사 추가", "요약 간결"]:
                r = apply_feedback(current, fb, raw_input="사업계획서")
                assert r.is_success
                versions = append_version(versions, r.new_doc, feedback_applied=fb)
                current = r.new_doc

        assert confirm_final(current).confirmed is True
        assert len(versions) == 4
        assert versions[0]["feedback_applied"] is None
        assert versions[1]["feedback_applied"] == "재무 강화"

    def test_llm_failure_preserves_current(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx
        with patch(_PATCH, side_effect=httpx.ConnectError("down")):
            current = _sample_doc("# 원본")
            r = apply_feedback(current, "피드백")
        assert r.is_success is False
        assert current["document"] == "# 원본"
