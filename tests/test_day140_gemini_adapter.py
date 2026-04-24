"""
Day 140 — Gemini 어댑터 테스트 (듀얼 모드 - Step 1 + Step 2)

Step 1 (기존):
  A. mode 파라미터
  B. is_available / API 키 우선순위
  C. Skipped when no key
  D. web_search 페이로드 / 응답 파싱 / 인용 / 차단
  E. Deep Research 기본 성공
  F. _extract_interaction_text
  G. _extract_interaction_citations
  H. 비용 계산 (모드별)
  I. 실사용 시나리오

Step 2 (신규):
  J. DR 폴링 타임아웃
  K. DR 중간 실패 상태 (failed/cancelled)
  L. DR Submit 실패
  M. DR 폴링 일시적 네트워크 복구
  N. _extract_error_message
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.research_v2.gemini_adapter import (
    GeminiResearchAdapter,
    MODE_WEB_SEARCH,
    MODE_DEEP_RESEARCH,
    _MODE_CONFIG,
    _get_api_key,
    _extract_text_from_parts,
    _extract_grounding_citations,
    _extract_interaction_text,
    _extract_interaction_citations,
    _extract_error_message,
    _calculate_cost,
)
from src.research_v2 import STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED


_HTTPX_POST_PATCH = "src.research_v2.gemini_adapter.httpx.post"
_HTTPX_GET_PATCH = "src.research_v2.gemini_adapter.httpx.get"
_TIME_SLEEP_PATCH = "src.research_v2.gemini_adapter.time.sleep"


# ===========================================================================
# 공통 mock 헬퍼
# ===========================================================================

def _mock_generate_content_success(
    text="리서치 보고서", grounding_chunks=None, usage=None, extra_parts=None
):
    r = MagicMock()
    r.status_code = 200
    parts = [{"text": text}]
    if extra_parts:
        parts.extend(extra_parts)
    candidate = {"content": {"parts": parts}}
    if grounding_chunks is not None:
        candidate["grounding_metadata"] = {"grounding_chunks": grounding_chunks}
    body = {"candidates": [candidate]}
    if usage is not None:
        body["usageMetadata"] = usage
    r.json.return_value = body
    return r


def _mock_http_error(status=500, text="Internal"):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


def _mock_interaction_submit(interaction_id="inter_new"):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"id": interaction_id, "status": "in_progress"}
    return r


def _mock_interaction_status(
    status="in_progress",
    interaction_id="inter_new",
    outputs=None,
    extra_fields=None,
):
    r = MagicMock()
    r.status_code = 200
    body = {"id": interaction_id, "status": status}
    if outputs is not None:
        body["outputs"] = outputs
    if extra_fields:
        body.update(extra_fields)
    r.json.return_value = body
    return r


def _mock_interaction_completed(
    text="# DR 최종 보고서",
    citations=None,
    usage=None,
    interaction_id="inter_new",
):
    outputs = [
        {"text": "중간 사고"},
        {"text": text},
    ]
    if citations:
        outputs[-1]["citations"] = citations
    return _mock_interaction_status(
        status="completed",
        interaction_id=interaction_id,
        outputs=outputs,
        extra_fields={"usage": usage} if usage else None,
    )


# ===========================================================================
# 공통 fixture — 환경변수 정리
# ===========================================================================

@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_RESEARCH_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_DEEP_RESEARCH_AGENT", raising=False)
    yield


# ===========================================================================
# A. mode 파라미터
# ===========================================================================

class TestModeParameter:
    def test_default_is_web_search(self):
        assert GeminiResearchAdapter().mode == MODE_WEB_SEARCH

    def test_explicit_web_search(self):
        assert GeminiResearchAdapter(mode="web_search").mode == "web_search"

    def test_explicit_deep_research(self):
        assert GeminiResearchAdapter(mode="deep_research").mode == "deep_research"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="invalid mode"):
            GeminiResearchAdapter(mode="invalid")

    def test_empty_mode_raises(self):
        with pytest.raises(ValueError):
            GeminiResearchAdapter(mode="")

    def test_web_search_default_timeout(self):
        assert GeminiResearchAdapter(mode="web_search").default_timeout == 300.0

    def test_deep_research_long_timeout(self):
        assert GeminiResearchAdapter(mode="deep_research").default_timeout == 1800.0

    def test_web_search_uses_background_false(self):
        assert GeminiResearchAdapter(mode="web_search")._config["uses_background"] is False

    def test_deep_research_uses_background_true(self):
        assert GeminiResearchAdapter(mode="deep_research")._config["uses_background"] is True


# ===========================================================================
# B. API 키
# ===========================================================================

class TestAvailability:
    def test_no_keys(self):
        assert GeminiResearchAdapter().is_available() is False

    def test_gemini_key_set(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gm-test")
        assert GeminiResearchAdapter().is_available() is True

    def test_google_key_fallback(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "gcp-test")
        assert GeminiResearchAdapter().is_available() is True

    def test_empty_keys(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("GOOGLE_API_KEY", "")
        assert GeminiResearchAdapter().is_available() is False

    def test_whitespace_keys(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "   ")
        assert GeminiResearchAdapter().is_available() is False


class TestKeyPriority:
    def test_gemini_preferred(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gm-primary")
        monkeypatch.setenv("GOOGLE_API_KEY", "gcp-secondary")
        assert _get_api_key() == "gm-primary"

    def test_google_fallback(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "gcp-only")
        assert _get_api_key() == "gcp-only"

    def test_empty(self):
        assert _get_api_key() == ""


# ===========================================================================
# C. Skipped when no key
# ===========================================================================

class TestSkippedWhenNoKey:
    def test_web_search_skipped(self):
        result = GeminiResearchAdapter(mode="web_search").research("q")
        assert result.status == STATUS_SKIPPED

    def test_deep_research_skipped(self):
        result = GeminiResearchAdapter(mode="deep_research").research("q")
        assert result.status == STATUS_SKIPPED


# ===========================================================================
# D. Web Search Payload / Success / Block / HTTP
# ===========================================================================

class TestWebSearchPayload:
    def test_url_and_headers(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gm-abc")
        adapter = GeminiResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return _mock_generate_content_success(text="ok")

        with patch(_HTTPX_POST_PATCH, side_effect=capture):
            adapter.research("질문", timeout=45)

        assert "generativelanguage.googleapis.com" in captured["url"]
        assert "gemini-3.1-pro-preview:generateContent" in captured["url"]
        assert captured["headers"]["x-goog-api-key"] == "gm-abc"
        assert captured["timeout"] == 45

    def test_tools_include_google_search(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_generate_content_success(text="ok")

        with patch(_HTTPX_POST_PATCH, side_effect=capture):
            adapter.research("q")

        assert {"google_search": {}} in captured["json"]["tools"]

    def test_user_query_in_contents(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_generate_content_success(text="ok")

        with patch(_HTTPX_POST_PATCH, side_effect=capture):
            adapter.research("특정 질문입니다")

        assert captured["json"]["contents"][0]["parts"][0]["text"] == "특정 질문입니다"

    def test_env_override_model(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        monkeypatch.setenv("GEMINI_RESEARCH_MODEL", "gemini-3-flash-preview")

        captured = {}

        def capture(url, **kwargs):
            captured["url"] = url
            return _mock_generate_content_success(text="ok")

        with patch(_HTTPX_POST_PATCH, side_effect=capture):
            GeminiResearchAdapter().research("q")

        assert "gemini-3-flash-preview" in captured["url"]


class TestWebSearchSuccess:
    def test_basic_success(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        with patch(_HTTPX_POST_PATCH, return_value=_mock_generate_content_success(
            text="# 보고서",
            grounding_chunks=[
                {"web": {"uri": "https://a.com", "title": "A"}},
                {"web": {"uri": "https://b.com", "title": "B"}},
            ],
            usage={"promptTokenCount": 100, "candidatesTokenCount": 2000},
        )):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert "보고서" in result.report
        assert len(result.citations) == 2
        assert result.model == "gemini-3.1-pro-preview"
        assert result.raw_meta["mode"] == "web_search"

    def test_no_grounding_chunks(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        with patch(_HTTPX_POST_PATCH, return_value=_mock_generate_content_success(text="x")):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.citations == []


class TestExtractTextFromParts:
    def test_single_part(self):
        assert _extract_text_from_parts({"parts": [{"text": "hello"}]}) == "hello"

    def test_multiple_parts_concatenated(self):
        content = {"parts": [{"text": "first "}, {"text": "second"}]}
        assert _extract_text_from_parts(content) == "first second"

    def test_non_text_parts_skipped(self):
        content = {"parts": [{"text": "Hello"}, {"inline_data": {"mime_type": "image/png"}}, {"text": " World"}]}
        assert _extract_text_from_parts(content) == "Hello World"

    def test_empty_parts(self):
        assert _extract_text_from_parts({"parts": []}) == ""

    def test_no_parts_field(self):
        assert _extract_text_from_parts({}) == ""

    def test_none_content(self):
        assert _extract_text_from_parts(None) == ""

    def test_non_dict_content(self):
        assert _extract_text_from_parts("not dict") == ""

    def test_part_with_none_text(self):
        content = {"parts": [{"text": None}, {"text": "valid"}]}
        assert _extract_text_from_parts(content) == "valid"


class TestGroundingCitations:
    def test_web_chunks_extracted(self):
        metadata = {"grounding_chunks": [
            {"web": {"uri": "https://a.com", "title": "A"}},
            {"web": {"uri": "https://b.com", "title": "B", "snippet": "desc"}},
        ]}
        result = _extract_grounding_citations(metadata)
        assert len(result) == 2
        assert result[1].snippet == "desc"

    def test_non_web_chunks_skipped(self):
        metadata = {"grounding_chunks": [
            {"web": {"uri": "https://a.com"}},
            {"retrievedContext": {"text": "..."}},
            {"web": {"uri": "https://b.com"}},
        ]}
        assert len(_extract_grounding_citations(metadata)) == 2

    def test_empty_uri_skipped(self):
        metadata = {"grounding_chunks": [
            {"web": {"uri": ""}},
            {"web": {"uri": "https://valid.com"}},
        ]}
        assert len(_extract_grounding_citations(metadata)) == 1

    def test_none_metadata(self):
        assert _extract_grounding_citations(None) == []

    def test_no_chunks_field(self):
        assert _extract_grounding_citations({}) == []

    def test_non_list_chunks(self):
        assert _extract_grounding_citations({"grounding_chunks": "not a list"}) == []

    def test_invalid_chunk_items(self):
        metadata = {"grounding_chunks": [
            {"web": {"uri": "https://a.com"}},
            "not a dict", None,
            {"no_web_field": {}},
        ]}
        assert len(_extract_grounding_citations(metadata)) == 1


class TestWebSearchBlockedResponse:
    def test_no_candidates_with_block_reason(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"promptFeedback": {"blockReason": "SAFETY"}}
        with patch(_HTTPX_POST_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "SAFETY" in (result.error or "")

    def test_no_candidates_no_block(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        with patch(_HTTPX_POST_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED

    def test_empty_report_with_finish_reason(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"candidates": [{
            "content": {"parts": []}, "finishReason": "RECITATION",
        }]}
        with patch(_HTTPX_POST_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "RECITATION" in (result.error or "")

    def test_candidate_not_dict(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"candidates": ["not a dict"]}
        with patch(_HTTPX_POST_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED


class TestWebSearchHTTPErrors:
    def test_400(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        with patch(_HTTPX_POST_PATCH, return_value=_mock_http_error(400)):
            result = GeminiResearchAdapter().research("q")
        assert result.status == STATUS_FAILED
        assert "400" in (result.error or "")

    def test_403(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "bad")
        with patch(_HTTPX_POST_PATCH, return_value=_mock_http_error(403)):
            result = GeminiResearchAdapter().research("q")
        assert result.status == STATUS_FAILED

    def test_500(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        with patch(_HTTPX_POST_PATCH, return_value=_mock_http_error(500)):
            result = GeminiResearchAdapter().research("q")
        assert result.status == STATUS_FAILED

    def test_network_exception(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        import httpx
        with patch(_HTTPX_POST_PATCH, side_effect=httpx.ConnectError("refused")):
            result = GeminiResearchAdapter().research("q")
        assert result.status == STATUS_FAILED


# ===========================================================================
# E. Deep Research 기본 성공
# ===========================================================================

class TestDeepResearchSuccess:
    def test_full_flow(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gm-dr")
        adapter = GeminiResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        submit = _mock_interaction_submit("inter_abc")
        in_progress = _mock_interaction_status("in_progress", "inter_abc")
        completed = _mock_interaction_completed(
            text="# Deep Research 보고서\n\n내용",
            citations=[
                {"uri": "https://src1.com", "title": "Source 1"},
                {"uri": "https://src2.com", "title": "Source 2"},
            ],
            usage={"promptTokenCount": 200, "candidatesTokenCount": 5000},
            interaction_id="inter_abc",
        )

        with patch(_HTTPX_POST_PATCH, return_value=submit), \
             patch(_HTTPX_GET_PATCH, side_effect=[in_progress, completed]), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("TPU 역사")

        assert result.status == STATUS_SUCCESS
        assert "Deep Research" in result.report
        assert len(result.citations) == 2
        assert result.citations[0].url == "https://src1.com"
        assert result.model == "deep-research-preview-04-2026"
        assert result.raw_meta["interaction_id"] == "inter_abc"
        assert result.raw_meta["mode"] == "deep_research"

    def test_immediate_completion(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        submit = _mock_interaction_submit("i1")
        completed = _mock_interaction_completed(text="즉시 완료", interaction_id="i1")

        with patch(_HTTPX_POST_PATCH, return_value=submit), \
             patch(_HTTPX_GET_PATCH, return_value=completed), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.is_success

    def test_submit_payload_has_background(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _mock_interaction_submit("i1")

        completed = _mock_interaction_completed(text="ok", interaction_id="i1")

        with patch(_HTTPX_POST_PATCH, side_effect=capture), \
             patch(_HTTPX_GET_PATCH, return_value=completed), \
             patch(_TIME_SLEEP_PATCH):
            adapter.research("q")

        assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/interactions"
        assert captured["json"]["background"] is True
        assert captured["json"]["agent"] == "deep-research-preview-04-2026"
        assert captured["json"]["input"] == "q"
        assert captured["headers"]["x-goog-api-key"] == "k"

    def test_dr_env_override_agent(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        monkeypatch.setenv("GEMINI_DEEP_RESEARCH_AGENT", "deep-research-max-preview-04-2026")
        adapter = GeminiResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_interaction_submit("i1")

        completed = _mock_interaction_completed(text="ok", interaction_id="i1")

        with patch(_HTTPX_POST_PATCH, side_effect=capture), \
             patch(_HTTPX_GET_PATCH, return_value=completed), \
             patch(_TIME_SLEEP_PATCH):
            adapter.research("q")

        assert captured["json"]["agent"] == "deep-research-max-preview-04-2026"


# ===========================================================================
# F. _extract_interaction_text
# ===========================================================================

class TestExtractInteractionText:
    def test_last_output_text(self):
        outputs = [{"text": "first"}, {"text": "second"}, {"text": "final"}]
        assert _extract_interaction_text(outputs) == "final"

    def test_empty_text_skipped(self):
        outputs = [{"text": "valid"}, {"text": ""}]
        assert _extract_interaction_text(outputs) == "valid"

    def test_whitespace_text_skipped(self):
        outputs = [{"text": "valid"}, {"text": "   "}]
        assert _extract_interaction_text(outputs) == "valid"

    def test_non_dict_items_skipped(self):
        outputs = ["string", None, {"text": "valid"}]
        assert _extract_interaction_text(outputs) == "valid"

    def test_none_input(self):
        assert _extract_interaction_text(None) == ""

    def test_non_list(self):
        assert _extract_interaction_text("x") == ""

    def test_empty_list(self):
        assert _extract_interaction_text([]) == ""


# ===========================================================================
# G. _extract_interaction_citations
# ===========================================================================

class TestExtractInteractionCitations:
    def test_citations_field(self):
        outputs = [
            {"text": "r", "citations": [
                {"uri": "https://a.com", "title": "A"},
                {"uri": "https://b.com"},
            ]},
        ]
        assert len(_extract_interaction_citations(outputs)) == 2

    def test_sources_field_alternative(self):
        outputs = [
            {"text": "r", "sources": [{"uri": "https://s.com", "title": "S"}]},
        ]
        result = _extract_interaction_citations(outputs)
        assert len(result) == 1
        assert result[0].url == "https://s.com"

    def test_duplicates_removed(self):
        outputs = [
            {"text": "r1", "citations": [{"uri": "https://a.com"}]},
            {"text": "r2", "citations": [{"uri": "https://a.com"}, {"uri": "https://b.com"}]},
        ]
        assert len(_extract_interaction_citations(outputs)) == 2

    def test_empty_url_skipped(self):
        outputs = [
            {"text": "r", "citations": [{"uri": ""}, {"uri": "https://valid.com"}]},
        ]
        assert len(_extract_interaction_citations(outputs)) == 1

    def test_url_field_alternative(self):
        outputs = [
            {"text": "r", "citations": [{"url": "https://a.com"}]},
        ]
        assert len(_extract_interaction_citations(outputs)) == 1

    def test_none_input(self):
        assert _extract_interaction_citations(None) == []

    def test_empty_outputs(self):
        assert _extract_interaction_citations([]) == []


# ===========================================================================
# H. 비용 계산
# ===========================================================================

class TestCalculateCost:
    def _web_cfg(self):
        return _MODE_CONFIG[MODE_WEB_SEARCH]

    def _dr_cfg(self):
        return _MODE_CONFIG[MODE_DEEP_RESEARCH]

    def test_web_search_basic(self):
        cost = _calculate_cost(
            {"promptTokenCount": 1000, "candidatesTokenCount": 2000},
            self._web_cfg(),
        )
        assert cost == pytest.approx(0.01125, abs=1e-6)

    def test_dr_same_rates(self):
        cost = _calculate_cost(
            {"promptTokenCount": 1000, "candidatesTokenCount": 2000},
            self._dr_cfg(),
        )
        assert cost == pytest.approx(0.01125, abs=1e-6)

    def test_interactions_snake_case(self):
        cost = _calculate_cost(
            {"input_tokens": 1000, "output_tokens": 2000},
            self._web_cfg(),
        )
        assert cost == pytest.approx(0.01125, abs=1e-6)

    def test_zero_usage(self):
        assert _calculate_cost({}, self._web_cfg()) == 0.0
        assert _calculate_cost(None, self._web_cfg()) == 0.0

    def test_non_dict(self):
        assert _calculate_cost("x", self._web_cfg()) == 0.0

    def test_negative_clamped(self):
        assert _calculate_cost(
            {"promptTokenCount": -100, "candidatesTokenCount": -50},
            self._web_cfg(),
        ) == 0.0

    def test_none_values(self):
        assert _calculate_cost(
            {"promptTokenCount": None, "candidatesTokenCount": None},
            self._web_cfg(),
        ) == 0.0

    def test_string_coerced(self):
        cost = _calculate_cost(
            {"promptTokenCount": "1000", "candidatesTokenCount": "500"},
            self._web_cfg(),
        )
        expected = (1000 * 1.25 + 500 * 5) / 1_000_000.0
        assert cost == pytest.approx(expected)


# ===========================================================================
# I. 실사용 시나리오
# ===========================================================================

class TestRealisticScenario:
    def test_web_search_realistic(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gm-real")
        adapter = GeminiResearchAdapter(mode="web_search")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{
                "content": {"parts": [
                    {"text": "# Coffee Guide\n\n## Stages"},
                    {"text": "\n\n1. Drying\n2. Maillard"},
                ]},
                "finishReason": "STOP",
                "grounding_metadata": {"grounding_chunks": [
                    {"web": {"uri": "https://scaa.org", "title": "SCAA"}},
                    {"web": {"uri": "https://sweetmarias.com", "title": "SM"}},
                ]},
            }],
            "usageMetadata": {"promptTokenCount": 150, "candidatesTokenCount": 2500},
        }

        with patch(_HTTPX_POST_PATCH, return_value=mock_resp):
            result = adapter.research("커피 로스팅")

        assert result.is_success
        assert "Coffee Guide" in result.report
        assert len(result.citations) == 2
        assert result.model == "gemini-3.1-pro-preview"

    def test_deep_research_realistic(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gm-real")
        adapter = GeminiResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=60.0,
        )

        submit = _mock_interaction_submit("inter_xyz")
        in_progress = _mock_interaction_status("in_progress", "inter_xyz")
        completed = _mock_interaction_status(
            status="completed",
            interaction_id="inter_xyz",
            outputs=[
                {"text": "초기 분석"},
                {"text": "## 최종 보고서\n\n15개 소스 기반 상세 분석",
                 "citations": [
                     {"uri": f"https://src{i}.com", "title": f"Source {i}"}
                     for i in range(10)
                 ]},
            ],
            extra_fields={"usage": {"input_tokens": 500, "output_tokens": 8000}},
        )

        with patch(_HTTPX_POST_PATCH, return_value=submit), \
             patch(_HTTPX_GET_PATCH, side_effect=[in_progress, in_progress, completed]), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("TPU 역사 심층 분석")

        assert result.is_success
        assert "최종 보고서" in result.report
        assert len(result.citations) == 10
        assert result.model == "deep-research-preview-04-2026"
        assert result.cost_usd == pytest.approx(0.040625, abs=1e-5)


# ===========================================================================
# ===========================================================================
# Step 2 추가 테스트 — 엣지 케이스
# ===========================================================================
# ===========================================================================


# ===========================================================================
# J. Deep Research 폴링 타임아웃
# ===========================================================================

class TestDeepResearchPollTimeout:
    def test_all_in_progress_times_out(self, monkeypatch):
        """모든 폴링이 in_progress → 타임아웃."""
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter(
            mode="deep_research",
            poll_interval=0.01,
            max_wait=0.03,  # 3번 폴링 후 타임아웃
        )

        submit = _mock_interaction_submit("r_timeout")
        in_progress = _mock_interaction_status("in_progress", "r_timeout")

        with patch(_HTTPX_POST_PATCH, return_value=submit), \
             patch(_HTTPX_GET_PATCH, return_value=in_progress), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "polling timeout" in (result.error or "")
        assert result.raw_meta.get("interaction_id") == "r_timeout"

    def test_max_wait_capped_by_timeout(self, monkeypatch):
        """timeout < max_wait 일 때 timeout이 우선."""
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter(
            mode="deep_research",
            poll_interval=0.01,
            max_wait=10.0,  # 10초까지 가능하지만
        )

        submit = _mock_interaction_submit("r_short")
        in_progress = _mock_interaction_status("in_progress", "r_short")

        with patch(_HTTPX_POST_PATCH, return_value=submit), \
             patch(_HTTPX_GET_PATCH, return_value=in_progress), \
             patch(_TIME_SLEEP_PATCH):
            # timeout=0.03 (3번 폴링) 으로 호출
            result = adapter.research("q", timeout=0.03)

        assert result.status == STATUS_FAILED
        assert "polling timeout" in (result.error or "")


# ===========================================================================
# K. Deep Research 중간 실패 상태
# ===========================================================================

class TestDeepResearchTerminalFailure:
    def test_failed_status_mid_polling(self, monkeypatch):
        """폴링 중 failed → 즉시 STATUS_FAILED."""
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        submit = _mock_interaction_submit("r_fail")
        in_progress = _mock_interaction_status("in_progress", "r_fail")
        failed = _mock_interaction_status(
            "failed", "r_fail",
            extra_fields={"error": {"message": "agent error", "code": "AGENT_ERROR"}},
        )

        with patch(_HTTPX_POST_PATCH, return_value=submit), \
             patch(_HTTPX_GET_PATCH, side_effect=[in_progress, failed]), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "failed" in (result.error or "")
        assert "agent error" in (result.error or "")
        assert result.raw_meta.get("interaction_id") == "r_fail"
        assert result.raw_meta.get("status") == "failed"

    def test_cancelled_status_mid_polling(self, monkeypatch):
        """폴링 중 cancelled."""
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        submit = _mock_interaction_submit("r_cancel")
        cancelled = _mock_interaction_status("cancelled", "r_cancel")

        with patch(_HTTPX_POST_PATCH, return_value=submit), \
             patch(_HTTPX_GET_PATCH, return_value=cancelled), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "cancelled" in (result.error or "")


# ===========================================================================
# L. Deep Research Submit 실패
# ===========================================================================

class TestDeepResearchSubmitFailure:
    def test_submit_401_unauthorized(self, monkeypatch):
        """Submit 시 401 → 폴링 시도 없이 실패."""
        monkeypatch.setenv("GEMINI_API_KEY", "bad")
        adapter = GeminiResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        with patch(_HTTPX_POST_PATCH, return_value=_mock_http_error(401, "Unauthorized")), \
             patch(_HTTPX_GET_PATCH) as mocked_get, \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "submit HTTP 401" in (result.error or "")
        assert mocked_get.call_count == 0

    def test_submit_missing_id(self, monkeypatch):
        """Submit 200 OK지만 body.id 없음."""
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "in_progress"}  # id 없음

        with patch(_HTTPX_POST_PATCH, return_value=mock_resp), \
             patch(_HTTPX_GET_PATCH) as mocked_get, \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "missing 'id'" in (result.error or "")
        assert mocked_get.call_count == 0

    def test_submit_timeout_exception(self, monkeypatch):
        """Submit 시 httpx.TimeoutException."""
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter(
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
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter(
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
# M. Deep Research 폴링 일시적 네트워크 복구
# ===========================================================================

class TestDeepResearchPollingRecovery:
    def test_transient_network_error_recovers(self, monkeypatch):
        """폴링 중 한 번 ConnectError → 다음 폴링에서 정상 → 성공."""
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )
        import httpx

        submit = _mock_interaction_submit("r_recover")
        completed = _mock_interaction_completed(
            text="복구 후 성공",
            usage={"promptTokenCount": 50, "candidatesTokenCount": 500},
            interaction_id="r_recover",
        )

        get_side_effects = [httpx.ConnectError("transient"), completed]

        with patch(_HTTPX_POST_PATCH, return_value=submit), \
             patch(_HTTPX_GET_PATCH, side_effect=get_side_effects), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert "복구 후 성공" in result.report

    def test_transient_5xx_recovers(self, monkeypatch):
        """폴링 중 5xx → 무시하고 계속 → 나중에 completed."""
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        submit = _mock_interaction_submit("r_5xx")
        server_error = _mock_http_error(503, "Service Unavailable")
        completed = _mock_interaction_completed(
            text="recovered",
            usage={"promptTokenCount": 50, "candidatesTokenCount": 500},
            interaction_id="r_5xx",
        )

        with patch(_HTTPX_POST_PATCH, return_value=submit), \
             patch(_HTTPX_GET_PATCH, side_effect=[server_error, completed]), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS


# ===========================================================================
# N. _extract_error_message
# ===========================================================================

class TestExtractErrorMessage:
    def test_error_dict_message_extracted(self):
        body = {"error": {"message": "rate limit exceeded", "code": "RATE_LIMIT"}}
        assert _extract_error_message(body) == "rate limit exceeded"

    def test_error_string_extracted(self):
        """error가 문자열인 경우도 지원."""
        body = {"error": "simple error string"}
        assert _extract_error_message(body) == "simple error string"

    def test_no_error_field_returns_empty(self):
        assert _extract_error_message({}) == ""
        assert _extract_error_message({"status": "failed"}) == ""

    def test_error_dict_no_message(self):
        body = {"error": {"code": "X", "type": "Y"}}
        assert _extract_error_message(body) == ""

    def test_error_empty_string(self):
        assert _extract_error_message({"error": ""}) == ""
