"""
Day 138 — Perplexity Sonar Deep Research 어댑터 테스트 (Phase 2 단계 2)

테스트 포인트:
  1. is_available — PERPLEXITY_API_KEY 있을 때만 True
  2. research() 진입 경로 (공통 research 흐름은 Day 137에서 검증)
  3. 응답 파싱 — report, citations, cost
  4. citations 포맷 다양성 (str / dict / 혼합 / 오염)
  5. 비용 계산 (input/output tokens + num_search_queries)
  6. HTTP 4xx / 5xx 처리
  7. 빈/malformed 응답 처리
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.research_v2.perplexity_adapter import (
    PerplexityDeepResearchAdapter,
    _parse_citations,
    _calculate_cost,
)
from src.research_v2 import STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED


_HTTPX_PATCH = "src.research_v2.perplexity_adapter.httpx.post"


def _mock_success(content="리서치 보고서", citations=None, usage=None):
    """Perplexity 성공 응답 mock."""
    r = MagicMock()
    r.status_code = 200

    body = {
        "choices": [{"message": {"content": content}}],
    }
    if citations is not None:
        body["citations"] = citations
    if usage is not None:
        body["usage"] = usage

    r.json.return_value = body
    return r


def _mock_error(status=500, text="Internal"):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


# ===========================================================================
# 1. is_available
# ===========================================================================

class TestAvailability:
    def test_no_key_unavailable(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        adapter = PerplexityDeepResearchAdapter()
        assert adapter.is_available() is False

    def test_key_set_available(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        adapter = PerplexityDeepResearchAdapter()
        assert adapter.is_available() is True

    def test_empty_key_unavailable(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "")
        adapter = PerplexityDeepResearchAdapter()
        assert adapter.is_available() is False

    def test_whitespace_key_unavailable(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "   ")
        adapter = PerplexityDeepResearchAdapter()
        assert adapter.is_available() is False


# ===========================================================================
# 2. research() — 키 없으면 skipped
# ===========================================================================

class TestSkippedWhenNoKey:
    def test_no_key_returns_skipped(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        adapter = PerplexityDeepResearchAdapter()
        result = adapter.research("test query")
        assert result.status == STATUS_SKIPPED
        assert result.adapter_name == "perplexity_sonar_dr"


# ===========================================================================
# 3. 정상 응답 파싱
# ===========================================================================

class TestSuccessfulParsing:
    def test_basic_success(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        adapter = PerplexityDeepResearchAdapter()

        mock_resp = _mock_success(
            content="# 커피 로스팅 보고서\n\n내용...",
            citations=["https://coffee.org", "https://example.edu"],
            usage={
                "prompt_tokens": 120,
                "completion_tokens": 3500,
                "num_search_queries": 25,
            },
        )
        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("커피 로스팅 가이드")

        assert result.status == STATUS_SUCCESS
        assert "커피 로스팅" in result.report
        assert len(result.citations) == 2
        assert result.citations[0].url == "https://coffee.org"
        assert result.model == "sonar-deep-research"
        assert result.cost_usd > 0

    def test_no_citations_still_success(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityDeepResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_success(content="report only")):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.report == "report only"
        assert result.citations == []

    def test_model_id_recorded(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityDeepResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_success(content="x")):
            result = adapter.research("q")

        assert result.model == "sonar-deep-research"

    def test_duration_measured(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityDeepResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_success(content="x")):
            result = adapter.research("q")

        assert result.duration_ms >= 0

    def test_request_payload_structure(self, monkeypatch):
        """Perplexity에 보내는 페이로드 검증."""
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-abc")
        adapter = PerplexityDeepResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return _mock_success(content="ok")

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("질문", timeout=60)

        assert "api.perplexity.ai" in captured["url"]
        assert captured["headers"]["Authorization"] == "Bearer pplx-abc"
        assert captured["json"]["model"] == "sonar-deep-research"
        assert len(captured["json"]["messages"]) == 2
        assert captured["json"]["messages"][1]["content"] == "질문"
        assert captured["timeout"] == 60


# ===========================================================================
# 4. citations 파싱 다양성
# ===========================================================================

class TestParseCitations:
    def test_url_string_list(self):
        result = _parse_citations(["https://a.com", "https://b.com"])
        assert len(result) == 2
        assert result[0].url == "https://a.com"
        assert result[0].title == ""

    def test_dict_list_with_titles(self):
        result = _parse_citations([
            {"url": "https://a.com", "title": "Article A"},
            {"url": "https://b.com", "title": "Article B", "snippet": "desc"},
        ])
        assert len(result) == 2
        assert result[1].snippet == "desc"

    def test_mixed_formats(self):
        result = _parse_citations([
            "https://x.com",
            {"url": "https://y.com", "title": "Y"},
        ])
        assert len(result) == 2
        assert result[0].url == "https://x.com"
        assert result[1].title == "Y"

    def test_empty_strings_filtered(self):
        result = _parse_citations(["", "https://a.com", "   "])
        assert len(result) == 1
        assert result[0].url == "https://a.com"

    def test_none_input_returns_empty(self):
        assert _parse_citations(None) == []

    def test_non_list_returns_empty(self):
        assert _parse_citations("not a list") == []
        assert _parse_citations(42) == []

    def test_dict_with_link_field(self):
        """일부 응답은 'url' 대신 'link' 필드."""
        result = _parse_citations([{"link": "https://a.com", "title": "A"}])
        assert len(result) == 1
        assert result[0].url == "https://a.com"

    def test_invalid_items_skipped(self):
        result = _parse_citations([
            {"url": "https://a.com"},
            None,
            123,
            {"title": "no url"},  # url 없음
            {"url": "https://b.com"},
        ])
        assert len(result) == 2


# ===========================================================================
# 5. 비용 계산
# ===========================================================================

class TestCalculateCost:
    def test_basic_formula(self):
        """
        1000 input + 3000 output + 20 searches
        = 1000×2/1M + 3000×8/1M + 20×5/1000
        = 0.002 + 0.024 + 0.10
        = 0.126
        """
        cost = _calculate_cost({
            "prompt_tokens": 1000,
            "completion_tokens": 3000,
            "num_search_queries": 20,
        })
        assert cost == pytest.approx(0.126, abs=1e-6)

    def test_zero_usage(self):
        assert _calculate_cost({}) == 0.0
        assert _calculate_cost(None) == 0.0

    def test_non_dict_usage(self):
        assert _calculate_cost("not dict") == 0.0
        assert _calculate_cost([]) == 0.0

    def test_missing_search_queries_field(self):
        """num_search_queries 없어도 토큰 비용은 계산."""
        cost = _calculate_cost({"prompt_tokens": 1000, "completion_tokens": 1000})
        expected = (1000 * 2 + 1000 * 8) / 1_000_000.0
        assert cost == pytest.approx(expected)

    def test_negative_tokens_clamped(self):
        cost = _calculate_cost({
            "prompt_tokens": -100,
            "completion_tokens": -50,
            "num_search_queries": -5,
        })
        assert cost == 0.0

    def test_none_values_treated_as_zero(self):
        cost = _calculate_cost({
            "prompt_tokens": None,
            "completion_tokens": None,
            "num_search_queries": None,
        })
        assert cost == 0.0

    def test_string_tokens_coerced(self):
        """API가 문자열로 숫자 내려줄 가능성 방어."""
        cost = _calculate_cost({
            "prompt_tokens": "1000",
            "completion_tokens": "500",
        })
        expected = (1000 * 2 + 500 * 8) / 1_000_000.0
        assert cost == pytest.approx(expected)

    def test_heavy_search_case(self):
        """검색 많으면 검색비용이 지배적."""
        cost = _calculate_cost({
            "prompt_tokens": 100,
            "completion_tokens": 500,
            "num_search_queries": 100,  # ~$0.50
        })
        assert cost > 0.4  # 검색비가 지배


# ===========================================================================
# 6. HTTP 에러 처리
# ===========================================================================

class TestHTTPErrors:
    def test_4xx_returns_failed(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityDeepResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_error(401, "Unauthorized")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "401" in (result.error or "")

    def test_5xx_returns_failed(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityDeepResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_error(500, "oops")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "500" in (result.error or "")

    def test_network_exception_returns_failed(self, monkeypatch):
        """httpx 예외 → base research()에서 캐치."""
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityDeepResearchAdapter()
        import httpx

        with patch(_HTTPX_PATCH, side_effect=httpx.ConnectError("refused")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "ConnectError" in (result.error or "")


# ===========================================================================
# 7. 비정상 응답
# ===========================================================================

class TestMalformedResponse:
    def test_missing_choices(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityDeepResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"error": "no choices"}

        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "malformed" in (result.error or "")

    def test_empty_content(self, monkeypatch):
        """content 가 빈 문자열이면 base가 failed로 downgrade."""
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityDeepResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_success(content="")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "empty report" in (result.error or "")

    def test_null_content(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityDeepResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": None}}],
        }
        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED


# ===========================================================================
# 8. 통합 시나리오
# ===========================================================================

class TestRealisticScenario:
    def test_full_perplexity_response(self, monkeypatch):
        """실제 Perplexity 응답 형태 시뮬레이션."""
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-real")
        adapter = PerplexityDeepResearchAdapter()

        # 실제 응답과 유사한 형태
        mock_resp = _mock_success(
            content="""# Advanced Coffee Roasting

## Overview
Coffee roasting is...

## Key Stages
1. Drying
2. Maillard reaction
3. First crack
...

## References
See citations below.
""",
            citations=[
                "https://scaa.org/roasting",
                "https://coffee-review.com/basics",
                "https://sweetmarias.com/learn",
            ],
            usage={
                "prompt_tokens": 150,
                "completion_tokens": 2800,
                "total_tokens": 2950,
                "num_search_queries": 22,
            },
        )

        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("커피 로스팅 심화 가이드")

        assert result.is_success
        assert "Coffee Roasting" in result.report
        assert len(result.citations) == 3
        assert result.citations[2].url == "https://sweetmarias.com/learn"
        assert result.model == "sonar-deep-research"
        # 150×2/1M + 2800×8/1M + 22×5/1000 ≈ 0.11
        assert 0.1 < result.cost_usd < 0.15
        assert "usage" in result.raw_meta
