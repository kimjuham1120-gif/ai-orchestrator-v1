"""
Day 140 — Google Gemini + google_search 어댑터 테스트 (Phase 2 단계 2)

테스트 포인트:
  1. is_available — GEMINI_API_KEY / GOOGLE_API_KEY 체크
  2. skipped when no key
  3. 페이로드 (tools, systemInstruction 포함)
  4. 정상 응답 파싱 (candidates + parts + grounding_chunks)
  5. parts 여러 개 이어붙이기
  6. grounding_chunks 중 web 만 인용으로 추출
  7. blockReason / finishReason 처리
  8. 비용 계산 (promptTokenCount / candidatesTokenCount)
  9. HTTP 에러
  10. API 키 우선순위 (GEMINI_API_KEY > GOOGLE_API_KEY)
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.research_v2.gemini_adapter import (
    GeminiResearchAdapter,
    _get_api_key,
    _extract_text_from_parts,
    _extract_grounding_citations,
    _calculate_cost,
)
from src.research_v2 import STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED


_HTTPX_PATCH = "src.research_v2.gemini_adapter.httpx.post"


def _mock_success(text="리서치 보고서", grounding_chunks=None, usage=None, extra_parts=None):
    r = MagicMock()
    r.status_code = 200
    parts = [{"text": text}]
    if extra_parts:
        parts.extend(extra_parts)
    candidate = {
        "content": {"parts": parts},
    }
    if grounding_chunks is not None:
        candidate["grounding_metadata"] = {"grounding_chunks": grounding_chunks}
    body = {"candidates": [candidate]}
    if usage is not None:
        body["usageMetadata"] = usage
    r.json.return_value = body
    return r


def _mock_error(status=500, text="Internal"):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """각 테스트 전에 API 키 env 정리."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_RESEARCH_MODEL", raising=False)
    yield


# ===========================================================================
# 1. is_available
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


# ===========================================================================
# 2. API 키 우선순위
# ===========================================================================

class TestKeyPriority:
    def test_gemini_key_preferred(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gm-primary")
        monkeypatch.setenv("GOOGLE_API_KEY", "gcp-secondary")
        assert _get_api_key() == "gm-primary"

    def test_google_fallback_when_no_gemini(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "gcp-only")
        assert _get_api_key() == "gcp-only"

    def test_empty_returns_empty(self):
        assert _get_api_key() == ""


# ===========================================================================
# 3. Skipped when no key
# ===========================================================================

class TestSkippedWhenNoKey:
    def test_skipped(self):
        result = GeminiResearchAdapter().research("q")
        assert result.status == STATUS_SKIPPED
        assert result.adapter_name == "gemini_grounded_research"


# ===========================================================================
# 4. 페이로드
# ===========================================================================

class TestRequestPayload:
    def test_url_and_headers(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gm-abc")
        adapter = GeminiResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return _mock_success(text="ok")

        with patch(_HTTPX_PATCH, side_effect=capture):
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
            return _mock_success(text="ok")

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("q")

        assert {"google_search": {}} in captured["json"]["tools"]

    def test_system_instruction_included(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success(text="ok")

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("q")

        sys_text = captured["json"]["systemInstruction"]["parts"][0]["text"]
        assert "research assistant" in sys_text.lower()

    def test_user_query_in_contents(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success(text="ok")

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("특정 질문입니다")

        user_text = captured["json"]["contents"][0]["parts"][0]["text"]
        assert user_text == "특정 질문입니다"

    def test_env_override_model(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        monkeypatch.setenv("GEMINI_RESEARCH_MODEL", "gemini-3-flash-preview")

        captured = {}

        def capture(url, **kwargs):
            captured["url"] = url
            return _mock_success(text="ok")

        with patch(_HTTPX_PATCH, side_effect=capture):
            GeminiResearchAdapter().research("q")

        assert "gemini-3-flash-preview" in captured["url"]


# ===========================================================================
# 5. 정상 응답 파싱
# ===========================================================================

class TestSuccessfulParsing:
    def test_basic_success(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_success(
            text="# 보고서\n\n내용",
            grounding_chunks=[
                {"web": {"uri": "https://a.com", "title": "A"}},
                {"web": {"uri": "https://b.com", "title": "B"}},
            ],
            usage={"promptTokenCount": 100, "candidatesTokenCount": 2000},
        )):
            result = adapter.research("질문")

        assert result.status == STATUS_SUCCESS
        assert "보고서" in result.report
        assert len(result.citations) == 2
        assert result.citations[0].url == "https://a.com"
        assert result.model == "gemini-3.1-pro-preview"
        assert result.cost_usd > 0

    def test_no_grounding_chunks_still_success(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_success(text="report")):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.citations == []


# ===========================================================================
# 6. parts 여러 개 이어붙이기
# ===========================================================================

class TestExtractTextFromParts:
    def test_single_part(self):
        content = {"parts": [{"text": "hello"}]}
        assert _extract_text_from_parts(content) == "hello"

    def test_multiple_parts_concatenated(self):
        content = {"parts": [{"text": "first "}, {"text": "second"}]}
        assert _extract_text_from_parts(content) == "first second"

    def test_non_text_parts_skipped(self):
        """text 없는 part (예: inline_data)는 건너뜀."""
        content = {
            "parts": [
                {"text": "Hello"},
                {"inline_data": {"mime_type": "image/png", "data": "..."}},
                {"text": " World"},
            ]
        }
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


# ===========================================================================
# 7. grounding_chunks 파싱
# ===========================================================================

class TestGroundingCitations:
    def test_web_chunks_extracted(self):
        metadata = {
            "grounding_chunks": [
                {"web": {"uri": "https://a.com", "title": "A"}},
                {"web": {"uri": "https://b.com", "title": "B", "snippet": "desc"}},
            ]
        }
        result = _extract_grounding_citations(metadata)
        assert len(result) == 2
        assert result[0].title == "A"
        assert result[1].snippet == "desc"

    def test_non_web_chunks_skipped(self):
        """retrievedContext 같은 non-web chunk는 제외."""
        metadata = {
            "grounding_chunks": [
                {"web": {"uri": "https://a.com"}},
                {"retrievedContext": {"text": "..."}},  # 제외
                {"web": {"uri": "https://b.com"}},
            ]
        }
        result = _extract_grounding_citations(metadata)
        assert len(result) == 2

    def test_empty_uri_skipped(self):
        metadata = {
            "grounding_chunks": [
                {"web": {"uri": ""}},
                {"web": {"uri": "https://valid.com"}},
            ]
        }
        result = _extract_grounding_citations(metadata)
        assert len(result) == 1

    def test_none_metadata(self):
        assert _extract_grounding_citations(None) == []

    def test_no_chunks_field(self):
        assert _extract_grounding_citations({}) == []

    def test_non_list_chunks(self):
        assert _extract_grounding_citations({"grounding_chunks": "not a list"}) == []

    def test_invalid_chunk_items(self):
        metadata = {
            "grounding_chunks": [
                {"web": {"uri": "https://a.com"}},
                "not a dict",
                None,
                {"no_web_field": {}},
            ]
        }
        result = _extract_grounding_citations(metadata)
        assert len(result) == 1


# ===========================================================================
# 8. blockReason / finishReason
# ===========================================================================

class TestBlockedResponse:
    def test_no_candidates_with_block_reason(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "promptFeedback": {"blockReason": "SAFETY"},
        }
        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "SAFETY" in (result.error or "")

    def test_no_candidates_no_block_reason(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "no candidates" in (result.error or "")

    def test_empty_report_with_finish_reason(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{
                "content": {"parts": []},
                "finishReason": "RECITATION",
            }]
        }
        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "RECITATION" in (result.error or "")

    def test_candidate_not_dict(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"candidates": ["not a dict"]}
        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED


# ===========================================================================
# 9. 비용 계산
# ===========================================================================

class TestCalculateCost:
    def test_basic_formula(self):
        """Gemini 3.1 Pro: $1.25/$5 per 1M."""
        cost = _calculate_cost({
            "promptTokenCount": 1000,
            "candidatesTokenCount": 2000,
        })
        # (1000×1.25 + 2000×5) / 1M = 0.00125 + 0.01 = 0.01125
        assert cost == pytest.approx(0.01125, abs=1e-6)

    def test_zero_usage(self):
        assert _calculate_cost({}) == 0.0
        assert _calculate_cost(None) == 0.0

    def test_non_dict(self):
        assert _calculate_cost("x") == 0.0

    def test_snake_case_field_ignored(self):
        """Gemini는 camelCase. snake_case는 무시됨."""
        cost = _calculate_cost({"prompt_tokens": 1000, "completion_tokens": 1000})
        assert cost == 0.0

    def test_negative_clamped(self):
        assert _calculate_cost({
            "promptTokenCount": -100,
            "candidatesTokenCount": -50,
        }) == 0.0

    def test_none_values(self):
        assert _calculate_cost({
            "promptTokenCount": None,
            "candidatesTokenCount": None,
        }) == 0.0

    def test_string_coerced(self):
        cost = _calculate_cost({
            "promptTokenCount": "1000",
            "candidatesTokenCount": "500",
        })
        expected = (1000 * 1.25 + 500 * 5) / 1_000_000.0
        assert cost == pytest.approx(expected)


# ===========================================================================
# 10. HTTP 에러
# ===========================================================================

class TestHTTPErrors:
    def test_400_bad_request(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_error(400, "Bad")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "400" in (result.error or "")

    def test_403_forbidden(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "bad")
        adapter = GeminiResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_error(403)):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED

    def test_500_error(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_error(500)):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED

    def test_network_exception(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        adapter = GeminiResearchAdapter()
        import httpx

        with patch(_HTTPX_PATCH, side_effect=httpx.ConnectError("refused")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "ConnectError" in (result.error or "")


# ===========================================================================
# 11. 실사용 시나리오
# ===========================================================================

class TestRealisticScenario:
    def test_full_gemini_response(self, monkeypatch):
        """실제 Gemini 응답 형태."""
        monkeypatch.setenv("GEMINI_API_KEY", "gm-real")
        adapter = GeminiResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": """# Coffee Roasting Guide

## Stages
1. Drying
2. Maillard
3. First crack
""",
                            },
                            {"text": "\n\n## Additional notes\nBe careful with temperature."},
                        ],
                    },
                    "finishReason": "STOP",
                    "grounding_metadata": {
                        "grounding_chunks": [
                            {"web": {"uri": "https://scaa.org", "title": "SCAA"}},
                            {"web": {"uri": "https://sweetmarias.com", "title": "Sweet Maria's"}},
                            {"web": {"uri": "https://coffee-review.com", "title": "Review"}},
                        ],
                        "search_entry_point": {"rendered_content": "<html>..."},
                    },
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 150,
                "candidatesTokenCount": 2500,
                "totalTokenCount": 2650,
            },
        }

        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("커피 로스팅 심화")

        assert result.is_success
        assert "Coffee Roasting" in result.report
        assert "Additional notes" in result.report  # 두 번째 part 포함
        assert len(result.citations) == 3
        assert result.model == "gemini-3.1-pro-preview"
        # 150×1.25/1M + 2500×5/1M = 0.0001875 + 0.0125 = 0.0126875
        assert result.cost_usd == pytest.approx(0.012688, abs=1e-5)
