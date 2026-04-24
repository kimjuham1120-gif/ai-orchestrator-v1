"""
Day 139 — OpenAI 어댑터 테스트 (듀얼 모드 - Step 1 + Step 2)

Step 1 범위 (기존):
  A. mode 파라미터 검증
  B. is_available
  C. Skipped when no key
  D. Web Search 모드 (하위호환)
  E. Deep Research 기본 성공 경로
  F. _extract_message_content
  G. _parse_annotations
  H. 비용 계산 (모드별)
  I. Web Search HTTP 에러
  J. 실사용 시나리오

Step 2 범위 (신규):
  K. Deep Research 폴링 타임아웃
  L. Deep Research 중간 실패 상태 (failed/cancelled/incomplete)
  M. Deep Research Submit 실패
  N. Deep Research 폴링 일시적 네트워크 복구
  O. 에러 메시지 추출
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.research_v2.openai_adapter import (
    OpenAIResearchAdapter,
    MODE_WEB_SEARCH,
    MODE_DEEP_RESEARCH,
    _MODE_CONFIG,
    _extract_message_content,
    _parse_annotations,
    _calculate_cost,
    _extract_error_message,
)
from src.research_v2 import STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED


_HTTPX_POST_PATCH = "src.research_v2.openai_adapter.httpx.post"
_HTTPX_GET_PATCH = "src.research_v2.openai_adapter.httpx.get"
_TIME_SLEEP_PATCH = "src.research_v2.openai_adapter.time.sleep"


# ===========================================================================
# 공통 mock 헬퍼
# ===========================================================================

def _build_message_output(text="리서치 보고서", annotations=None):
    content_item = {"type": "output_text", "text": text}
    if annotations is not None:
        content_item["annotations"] = annotations
    return {
        "type": "message",
        "role": "assistant",
        "content": [content_item],
    }


def _mock_success(text="응답", annotations=None, usage=None, extra_outputs=None,
                   response_id="resp_abc123", status="completed"):
    r = MagicMock()
    r.status_code = 200
    output = list(extra_outputs or [])
    output.append(_build_message_output(text, annotations))
    body = {"id": response_id, "status": status, "output": output}
    if usage is not None:
        body["usage"] = usage
    r.json.return_value = body
    return r


def _mock_error(status=500, text="Internal"):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


def _mock_queued(response_id="resp_new"):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"id": response_id, "status": "queued"}
    return r


def _mock_polling_status(status="in_progress", response_id="resp_new",
                          extra_fields=None):
    r = MagicMock()
    r.status_code = 200
    body = {"id": response_id, "status": status}
    if extra_fields:
        body.update(extra_fields)
    r.json.return_value = body
    return r


# ===========================================================================
# A. mode 파라미터 검증
# ===========================================================================

class TestModeParameter:
    def test_default_mode_is_web_search(self):
        adapter = OpenAIResearchAdapter()
        assert adapter.mode == MODE_WEB_SEARCH

    def test_explicit_web_search(self):
        adapter = OpenAIResearchAdapter(mode="web_search")
        assert adapter.mode == "web_search"

    def test_explicit_deep_research(self):
        adapter = OpenAIResearchAdapter(mode="deep_research")
        assert adapter.mode == "deep_research"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="invalid mode"):
            OpenAIResearchAdapter(mode="invalid")

    def test_empty_mode_raises(self):
        with pytest.raises(ValueError):
            OpenAIResearchAdapter(mode="")

    def test_web_search_uses_background_false(self):
        adapter = OpenAIResearchAdapter(mode="web_search")
        assert adapter._config["uses_background"] is False

    def test_deep_research_uses_background_true(self):
        adapter = OpenAIResearchAdapter(mode="deep_research")
        assert adapter._config["uses_background"] is True

    def test_web_search_default_timeout(self):
        adapter = OpenAIResearchAdapter(mode="web_search")
        assert adapter.default_timeout == 300.0

    def test_deep_research_long_timeout(self):
        adapter = OpenAIResearchAdapter(mode="deep_research")
        assert adapter.default_timeout == 1200.0


# ===========================================================================
# B. is_available
# ===========================================================================

class TestAvailability:
    def test_no_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert OpenAIResearchAdapter().is_available() is False

    def test_with_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert OpenAIResearchAdapter().is_available() is True

    def test_empty_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "")
        assert OpenAIResearchAdapter().is_available() is False

    def test_whitespace_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "   ")
        assert OpenAIResearchAdapter().is_available() is False


# ===========================================================================
# C. Skipped when no key
# ===========================================================================

class TestSkippedWhenNoKey:
    def test_web_search_skipped(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = OpenAIResearchAdapter(mode="web_search").research("q")
        assert result.status == STATUS_SKIPPED

    def test_deep_research_skipped(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = OpenAIResearchAdapter(mode="deep_research").research("q")
        assert result.status == STATUS_SKIPPED


# ===========================================================================
# D. Web Search Payload
# ===========================================================================

class TestWebSearchPayload:
    def test_payload_structure(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-abc")
        adapter = OpenAIResearchAdapter(mode="web_search")

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return _mock_success(text="ok")

        with patch(_HTTPX_POST_PATCH, side_effect=capture):
            adapter.research("질문", timeout=60)

        assert captured["url"] == "https://api.openai.com/v1/responses"
        assert captured["headers"]["Authorization"] == "Bearer sk-abc"
        assert captured["timeout"] == 60

        payload = captured["json"]
        assert payload["model"] == "gpt-5.4"
        assert payload["input"][1]["content"][0]["text"] == "질문"
        assert {"type": "web_search_preview"} in payload["tools"]
        assert "background" not in payload

    def test_env_override_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("OPENAI_RESEARCH_MODEL", "gpt-4o")
        adapter = OpenAIResearchAdapter(mode="web_search")

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success(text="ok")

        with patch(_HTTPX_POST_PATCH, side_effect=capture):
            adapter.research("q")

        assert captured["json"]["model"] == "gpt-4o"

    def test_blank_env_uses_default(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("OPENAI_RESEARCH_MODEL", "   ")
        adapter = OpenAIResearchAdapter(mode="web_search")

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success(text="ok")

        with patch(_HTTPX_POST_PATCH, side_effect=capture):
            adapter.research("q")

        assert captured["json"]["model"] == "gpt-5.4"


# ===========================================================================
# D-2. Web Search Success
# ===========================================================================

class TestWebSearchSuccess:
    def test_basic_success(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")

        with patch(_HTTPX_POST_PATCH, return_value=_mock_success(
            text="# 보고서\n\n내용",
            annotations=[
                {"type": "url_citation", "url": "https://a.com", "title": "A"},
                {"type": "url_citation", "url": "https://b.com", "title": "B"},
            ],
            usage={"input_tokens": 100, "output_tokens": 2000},
        )):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert "보고서" in result.report
        assert len(result.citations) == 2
        assert result.model == "gpt-5.4"
        assert result.cost_usd > 0
        assert result.raw_meta["mode"] == "web_search"

    def test_no_annotations_still_success(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")

        with patch(_HTTPX_POST_PATCH, return_value=_mock_success(text="report")):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.citations == []

    def test_web_search_calls_ignored(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")

        extra = [
            {"type": "web_search_call", "status": "completed"},
            {"type": "web_search_call", "status": "completed"},
        ]
        with patch(_HTTPX_POST_PATCH, return_value=_mock_success(
            text="final report", extra_outputs=extra
        )):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.report == "final report"


class TestWebSearchResponseStatus:
    def test_failed_status(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "r", "status": "failed", "output": []}
        with patch(_HTTPX_POST_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "failed" in (result.error or "")

    def test_cancelled_status(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "r", "status": "cancelled", "output": []}
        with patch(_HTTPX_POST_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED


# ===========================================================================
# E. Deep Research 기본 성공
# ===========================================================================

class TestDeepResearchSuccess:
    def test_submit_then_poll_completes(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-dr")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        submit_resp = _mock_queued("resp_dr_123")
        in_progress = _mock_polling_status("in_progress", "resp_dr_123")
        completed = _mock_success(
            text="# Deep Research 보고서\n\n내용",
            annotations=[
                {"type": "url_citation", "url": "https://src1.com", "title": "S1"},
                {"type": "url_citation", "url": "https://src2.com", "title": "S2"},
            ],
            usage={"input_tokens": 200, "output_tokens": 5000},
            response_id="resp_dr_123", status="completed",
        )

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, side_effect=[in_progress, completed]), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("커피 로스팅 심층 분석")

        assert result.status == STATUS_SUCCESS
        assert "Deep Research" in result.report
        assert len(result.citations) == 2
        assert result.model == "o4-mini-deep-research-2025-06-26"
        assert result.raw_meta["mode"] == "deep_research"
        assert result.raw_meta["response_id"] == "resp_dr_123"
        assert result.cost_usd == pytest.approx(0.0404, abs=1e-4)

    def test_immediate_completion(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        submit_resp = _mock_queued("r1")
        completed = _mock_success(
            text="결과", usage={"input_tokens": 100, "output_tokens": 500},
            response_id="r1", status="completed",
        )

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, return_value=completed), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.is_success

    def test_submit_payload_has_background(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        captured = {}

        def capture_submit(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_queued("r1")

        completed = _mock_success(text="ok", response_id="r1", status="completed")

        with patch(_HTTPX_POST_PATCH, side_effect=capture_submit), \
             patch(_HTTPX_GET_PATCH, return_value=completed), \
             patch(_TIME_SLEEP_PATCH):
            adapter.research("q")

        assert captured["json"]["background"] is True
        assert captured["json"]["model"] == "o4-mini-deep-research-2025-06-26"
        assert {"type": "web_search_preview"} in captured["json"]["tools"]

    def test_dr_env_override_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("OPENAI_DEEP_RESEARCH_MODEL", "o3-deep-research-2025-06-26")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_queued("r1")

        completed = _mock_success(text="ok", response_id="r1", status="completed")

        with patch(_HTTPX_POST_PATCH, side_effect=capture), \
             patch(_HTTPX_GET_PATCH, return_value=completed), \
             patch(_TIME_SLEEP_PATCH):
            adapter.research("q")

        assert captured["json"]["model"] == "o3-deep-research-2025-06-26"


# ===========================================================================
# F. _extract_message_content
# ===========================================================================

class TestExtractMessageContent:
    def test_single_message(self):
        output = [_build_message_output("hello", [])]
        text, citations = _extract_message_content(output)
        assert text == "hello"
        assert citations == []

    def test_multiple_messages_last_wins(self):
        output = [
            _build_message_output("first", []),
            _build_message_output("second", []),
        ]
        text, _ = _extract_message_content(output)
        assert text == "second"

    def test_no_message_returns_empty(self):
        output = [{"type": "web_search_call"}, {"type": "reasoning"}]
        text, citations = _extract_message_content(output)
        assert text == ""
        assert citations == []

    def test_none_input(self):
        assert _extract_message_content(None) == ("", [])

    def test_non_list_input(self):
        assert _extract_message_content("not a list") == ("", [])

    def test_malformed_content(self):
        output = [{"type": "message", "content": []}]
        text, _ = _extract_message_content(output)
        assert text == ""

    def test_missing_content_field(self):
        output = [{"type": "message"}]
        text, _ = _extract_message_content(output)
        assert text == ""


# ===========================================================================
# G. _parse_annotations
# ===========================================================================

class TestParseAnnotations:
    def test_url_citations(self):
        result = _parse_annotations([
            {"type": "url_citation", "url": "https://a", "title": "A"},
            {"type": "url_citation", "url": "https://b"},
        ])
        assert len(result) == 2

    def test_non_url_citation_skipped(self):
        result = _parse_annotations([
            {"type": "url_citation", "url": "https://a"},
            {"type": "file_citation", "file_id": "f_123"},
        ])
        assert len(result) == 1

    def test_empty_url_skipped(self):
        result = _parse_annotations([
            {"type": "url_citation", "url": ""},
            {"type": "url_citation", "url": "https://valid"},
        ])
        assert len(result) == 1

    def test_none_input(self):
        assert _parse_annotations(None) == []

    def test_non_list_input(self):
        assert _parse_annotations("x") == []
        assert _parse_annotations(42) == []

    def test_non_dict_items_skipped(self):
        result = _parse_annotations([
            "not a dict", None,
            {"type": "url_citation", "url": "https://a"},
        ])
        assert len(result) == 1


# ===========================================================================
# H. 비용 계산
# ===========================================================================

class TestCalculateCostWebSearch:
    def _config(self):
        return _MODE_CONFIG[MODE_WEB_SEARCH]

    def test_basic_formula(self):
        cost = _calculate_cost(
            {"input_tokens": 1000, "output_tokens": 2000},
            self._config(),
        )
        assert cost == pytest.approx(0.0325, abs=1e-6)


class TestCalculateCostDeepResearch:
    def _config(self):
        return _MODE_CONFIG[MODE_DEEP_RESEARCH]

    def test_basic_formula(self):
        cost = _calculate_cost(
            {"input_tokens": 1000, "output_tokens": 2000},
            self._config(),
        )
        assert cost == pytest.approx(0.018, abs=1e-6)


class TestCalculateCostDefensive:
    def _any_config(self):
        return _MODE_CONFIG[MODE_WEB_SEARCH]

    def test_zero_usage(self):
        assert _calculate_cost({}, self._any_config()) == 0.0
        assert _calculate_cost(None, self._any_config()) == 0.0

    def test_non_dict(self):
        assert _calculate_cost("x", self._any_config()) == 0.0

    def test_negative_clamped(self):
        assert _calculate_cost(
            {"input_tokens": -100, "output_tokens": -50},
            self._any_config(),
        ) == 0.0

    def test_none_values(self):
        assert _calculate_cost(
            {"input_tokens": None, "output_tokens": None},
            self._any_config(),
        ) == 0.0

    def test_string_coerced(self):
        cost = _calculate_cost(
            {"input_tokens": "1000", "output_tokens": "500"},
            self._any_config(),
        )
        expected = (1000 * 2.5 + 500 * 15) / 1_000_000.0
        assert cost == pytest.approx(expected)

    def test_prompt_tokens_ignored(self):
        cost = _calculate_cost(
            {"prompt_tokens": 1000, "completion_tokens": 1000},
            self._any_config(),
        )
        assert cost == 0.0


# ===========================================================================
# I. Web Search HTTP 에러
# ===========================================================================

class TestWebSearchHTTPErrors:
    def test_401(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "bad")
        adapter = OpenAIResearchAdapter(mode="web_search")

        with patch(_HTTPX_POST_PATCH, return_value=_mock_error(401)):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "401" in (result.error or "")

    def test_500(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")

        with patch(_HTTPX_POST_PATCH, return_value=_mock_error(500)):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED

    def test_network_exception(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")
        import httpx

        with patch(_HTTPX_POST_PATCH, side_effect=httpx.ConnectError("refused")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "ConnectError" in (result.error or "")


# ===========================================================================
# J. 실사용 시나리오
# ===========================================================================

class TestRealisticScenario:
    def test_web_search_realistic(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
        adapter = OpenAIResearchAdapter(mode="web_search")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "resp_abc", "status": "completed",
            "output": [
                {"type": "web_search_call", "status": "completed"},
                _build_message_output(
                    "# Coffee Roasting\n\n## Stages\n1. Drying\n2. Maillard",
                    annotations=[
                        {"type": "url_citation", "url": "https://scaa.org", "title": "SCAA"},
                    ],
                ),
            ],
            "usage": {"input_tokens": 150, "output_tokens": 2500},
        }

        with patch(_HTTPX_POST_PATCH, return_value=mock_resp):
            result = adapter.research("커피 로스팅")

        assert result.is_success
        assert result.model == "gpt-5.4"
        assert result.cost_usd == pytest.approx(0.037875, abs=1e-5)

    def test_deep_research_realistic(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=60.0,
        )

        submit_resp = _mock_queued("resp_dr_xyz")
        in_progress_resp = _mock_polling_status("in_progress", "resp_dr_xyz")
        completed_resp = _mock_success(
            text="# Deep Coffee Report\n\n[15 sources, 3000 words]",
            annotations=[
                {"type": "url_citation", "url": f"https://source{i}.com", "title": f"S{i}"}
                for i in range(5)
            ],
            usage={"input_tokens": 300, "output_tokens": 4500},
            response_id="resp_dr_xyz", status="completed",
        )

        get_responses = [in_progress_resp, in_progress_resp, completed_resp]

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, side_effect=get_responses), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("커피 로스팅 심층 분석")

        assert result.is_success
        assert len(result.citations) == 5
        assert result.model == "o4-mini-deep-research-2025-06-26"
        assert result.cost_usd == pytest.approx(0.0366, abs=1e-4)


# ===========================================================================
# ===========================================================================
# Step 2 추가 테스트 — 엣지 케이스
# ===========================================================================
# ===========================================================================


# ===========================================================================
# K. Deep Research 폴링 타임아웃
# ===========================================================================

class TestDeepResearchPollTimeout:
    def test_all_in_progress_times_out(self, monkeypatch):
        """모든 폴링이 in_progress → 타임아웃 → STATUS_FAILED."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research",
            poll_interval=0.01,
            max_wait=0.03,  # 3번 폴링 후 타임아웃
        )

        submit_resp = _mock_queued("r_timeout")
        in_progress = _mock_polling_status("in_progress", "r_timeout")

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, return_value=in_progress), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "polling timeout" in (result.error or "")
        assert result.raw_meta.get("response_id") == "r_timeout"

    def test_queued_only_times_out(self, monkeypatch):
        """queued 상태로만 계속 머무름 → 타임아웃."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=0.03,
        )

        submit_resp = _mock_queued("r_stuck")
        queued = _mock_polling_status("queued", "r_stuck")

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, return_value=queued), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "polling timeout" in (result.error or "")


# ===========================================================================
# L. Deep Research 중간 실패 상태
# ===========================================================================

class TestDeepResearchTerminalFailure:
    def test_failed_status_mid_polling(self, monkeypatch):
        """폴링 중 failed → 즉시 STATUS_FAILED 반환."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        submit_resp = _mock_queued("r_fail")
        in_progress = _mock_polling_status("in_progress", "r_fail")
        failed = _mock_polling_status(
            "failed", "r_fail",
            extra_fields={"error": {"message": "model error", "type": "server_error"}},
        )

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, side_effect=[in_progress, failed]), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "failed" in (result.error or "")
        assert "model error" in (result.error or "")
        assert result.raw_meta.get("response_id") == "r_fail"
        assert result.raw_meta.get("status") == "failed"

    def test_cancelled_status_mid_polling(self, monkeypatch):
        """폴링 중 cancelled."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        submit_resp = _mock_queued("r_cancel")
        cancelled = _mock_polling_status("cancelled", "r_cancel")

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, return_value=cancelled), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "cancelled" in (result.error or "")

    def test_incomplete_status_with_reason(self, monkeypatch):
        """incomplete 상태 + incomplete_details.reason 메시지 추출."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        submit_resp = _mock_queued("r_incomplete")
        incomplete = _mock_polling_status(
            "incomplete", "r_incomplete",
            extra_fields={"incomplete_details": {"reason": "max_output_tokens"}},
        )

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, return_value=incomplete), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "incomplete" in (result.error or "")
        assert "max_output_tokens" in (result.error or "")


# ===========================================================================
# M. Deep Research Submit 실패
# ===========================================================================

class TestDeepResearchSubmitFailure:
    def test_submit_401_unauthorized(self, monkeypatch):
        """Submit 시 401 → 폴링 시도 없이 실패."""
        monkeypatch.setenv("OPENAI_API_KEY", "bad")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        mock_get = MagicMock()  # 폴링이 호출되면 안 됨

        with patch(_HTTPX_POST_PATCH, return_value=_mock_error(401, "Unauthorized")), \
             patch(_HTTPX_GET_PATCH) as mocked_get, \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "submit HTTP 401" in (result.error or "")
        # 폴링 시도 없어야 함
        assert mocked_get.call_count == 0

    def test_submit_missing_id(self, monkeypatch):
        """Submit 200 OK지만 body.id 없음."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "queued"}  # id 없음

        with patch(_HTTPX_POST_PATCH, return_value=mock_resp), \
             patch(_HTTPX_GET_PATCH) as mocked_get, \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "missing 'id'" in (result.error or "")
        assert mocked_get.call_count == 0

    def test_submit_timeout_exception(self, monkeypatch):
        """Submit 시 httpx.TimeoutException → 실패."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )
        import httpx

        with patch(_HTTPX_POST_PATCH, side_effect=httpx.ReadTimeout("slow")), \
             patch(_HTTPX_GET_PATCH), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "submit timeout" in (result.error or "")

    def test_submit_network_error(self, monkeypatch):
        """Submit 시 네트워크 오류."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )
        import httpx

        with patch(_HTTPX_POST_PATCH, side_effect=httpx.ConnectError("refused")), \
             patch(_HTTPX_GET_PATCH), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "submit error" in (result.error or "")


# ===========================================================================
# N. Deep Research 폴링 중 일시적 네트워크 오류
# ===========================================================================

class TestDeepResearchPollingRecovery:
    def test_transient_network_error_recovers(self, monkeypatch):
        """폴링 중 한 번 네트워크 오류 → 다음 폴링에서 정상 → 성공."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )
        import httpx

        submit_resp = _mock_queued("r_recover")
        completed = _mock_success(
            text="복구 후 성공", usage={"input_tokens": 50, "output_tokens": 500},
            response_id="r_recover", status="completed",
        )

        # 첫 폴링: ConnectError → 무시 → 두 번째 폴링: completed
        get_side_effects = [httpx.ConnectError("transient"), completed]

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, side_effect=get_side_effects), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert "복구 후 성공" in result.report

    def test_transient_5xx_recovers(self, monkeypatch):
        """폴링 중 5xx → 무시하고 계속 → 나중에 completed."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        submit_resp = _mock_queued("r_5xx")
        server_error = _mock_error(503, "Service Unavailable")
        completed = _mock_success(
            text="recovered", usage={"input_tokens": 50, "output_tokens": 500},
            response_id="r_5xx", status="completed",
        )

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, side_effect=[server_error, completed]), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS


# ===========================================================================
# O. 에러 메시지 추출 헬퍼
# ===========================================================================

class TestExtractErrorMessage:
    def test_error_message_extracted(self):
        body = {"error": {"message": "rate limit exceeded", "type": "rate_limit"}}
        assert _extract_error_message(body) == "rate limit exceeded"

    def test_incomplete_details_reason_extracted(self):
        body = {"incomplete_details": {"reason": "max_output_tokens"}}
        assert _extract_error_message(body) == "max_output_tokens"

    def test_no_error_fields_returns_empty(self):
        assert _extract_error_message({}) == ""
        assert _extract_error_message({"status": "failed"}) == ""

    def test_error_not_dict_returns_empty(self):
        assert _extract_error_message({"error": "string not dict"}) == ""

    def test_empty_message_returns_empty(self):
        body = {"error": {"message": "", "type": "x"}}
        assert _extract_error_message(body) == ""
