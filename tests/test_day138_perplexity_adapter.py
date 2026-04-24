"""
Day 138 — Perplexity 어댑터 테스트 (듀얼 모드 지원)

검증:
  1. is_available — PERPLEXITY_API_KEY 있을 때만 True
  2. mode 파라미터 (web_search / deep_research / invalid)
  3. 모드별 모델 ID / 타임아웃
  4. 응답 파싱 — report, citations, cost
  5. citations 포맷 다양성 (str / dict / 혼합 / 오염)
  6. 모드별 비용 계산
     - web_search: input + output만
     - deep_research: + num_search_queries × $5/1000
  7. HTTP 4xx / 5xx
  8. malformed 응답
  9. 하위호환 (PerplexityDeepResearchAdapter)
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.research_v2.perplexity_adapter import (
    PerplexityResearchAdapter,
    PerplexityDeepResearchAdapter,
    MODE_WEB_SEARCH,
    MODE_DEEP_RESEARCH,
    _parse_citations,
    _calculate_cost,
    _MODE_CONFIG,
)
from src.research_v2 import STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED


_HTTPX_PATCH = "src.research_v2.perplexity_adapter.httpx.post"


def _mock_success(content="리서치 보고서", citations=None, usage=None):
    r = MagicMock()
    r.status_code = 200
    body = {"choices": [{"message": {"content": content}}]}
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
# 1. mode 파라미터 검증
# ===========================================================================

class TestModeParameter:
    def test_default_mode_is_web_search(self):
        adapter = PerplexityResearchAdapter()
        assert adapter.mode == MODE_WEB_SEARCH

    def test_explicit_web_search_mode(self):
        adapter = PerplexityResearchAdapter(mode="web_search")
        assert adapter.mode == "web_search"

    def test_explicit_deep_research_mode(self):
        adapter = PerplexityResearchAdapter(mode="deep_research")
        assert adapter.mode == "deep_research"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="invalid mode"):
            PerplexityResearchAdapter(mode="invalid_mode")

    def test_empty_mode_raises(self):
        with pytest.raises(ValueError):
            PerplexityResearchAdapter(mode="")

    def test_web_search_uses_sonar_pro(self):
        adapter = PerplexityResearchAdapter(mode="web_search")
        assert adapter._config["model"] == "sonar-pro"

    def test_deep_research_uses_sonar_dr(self):
        adapter = PerplexityResearchAdapter(mode="deep_research")
        assert adapter._config["model"] == "sonar-deep-research"

    def test_web_search_has_short_timeout(self):
        adapter = PerplexityResearchAdapter(mode="web_search")
        assert adapter.default_timeout == 60.0

    def test_deep_research_has_long_timeout(self):
        adapter = PerplexityResearchAdapter(mode="deep_research")
        assert adapter.default_timeout == 600.0


# ===========================================================================
# 2. is_available
# ===========================================================================

class TestAvailability:
    def test_no_key(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        assert PerplexityResearchAdapter().is_available() is False

    def test_with_key(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        assert PerplexityResearchAdapter().is_available() is True

    def test_empty_key(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "")
        assert PerplexityResearchAdapter().is_available() is False

    def test_whitespace_key(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "   ")
        assert PerplexityResearchAdapter().is_available() is False

    def test_availability_same_across_modes(self, monkeypatch):
        """모드 무관하게 환경변수만 체크."""
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        assert PerplexityResearchAdapter(mode="web_search").is_available() is True
        assert PerplexityResearchAdapter(mode="deep_research").is_available() is True


# ===========================================================================
# 3. skipped when no key
# ===========================================================================

class TestSkippedWhenNoKey:
    def test_skipped(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        result = PerplexityResearchAdapter().research("q")
        assert result.status == STATUS_SKIPPED
        assert result.adapter_name == "perplexity_research"


# ===========================================================================
# 4. 모드별 성공 경로
# ===========================================================================

class TestWebSearchMode:
    def test_basic_success(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter(mode="web_search")

        with patch(_HTTPX_PATCH, return_value=_mock_success(
            content="# 빠른 보고서",
            citations=["https://a.com"],
            usage={"prompt_tokens": 100, "completion_tokens": 500},
        )):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.model == "sonar-pro"
        assert result.raw_meta["mode"] == "web_search"
        # 100×3/1M + 500×15/1M = 0.0003 + 0.0075 = 0.0078
        assert result.cost_usd == pytest.approx(0.0078, abs=1e-5)

    def test_payload_uses_sonar_pro(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter(mode="web_search")

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            captured["timeout"] = timeout
            return _mock_success()

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("q", timeout=60)

        assert captured["json"]["model"] == "sonar-pro"
        assert captured["timeout"] == 60


class TestDeepResearchMode:
    def test_basic_success(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter(mode="deep_research")

        with patch(_HTTPX_PATCH, return_value=_mock_success(
            content="# 심층 보고서",
            citations=["https://a.com", "https://b.com"],
            usage={
                "prompt_tokens": 120,
                "completion_tokens": 3500,
                "num_search_queries": 25,
            },
        )):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.model == "sonar-deep-research"
        assert result.raw_meta["mode"] == "deep_research"
        # 120×2/1M + 3500×8/1M + 25×5/1000 = 0.00024 + 0.028 + 0.125 = 0.15324
        assert result.cost_usd == pytest.approx(0.15324, abs=1e-4)

    def test_payload_uses_sonar_deep_research(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter(mode="deep_research")

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success()

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("q")

        assert captured["json"]["model"] == "sonar-deep-research"


# ===========================================================================
# 5. 공통 성공 케이스 (mode 무관)
# ===========================================================================

class TestSuccessfulParsing:
    def test_no_citations_still_success(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_success(content="report only")):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.citations == []

    def test_duration_measured(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_success(content="x")):
            result = adapter.research("q")

        assert result.duration_ms >= 0

    def test_request_headers(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-abc")
        adapter = PerplexityResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            return _mock_success()

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("q")

        assert "api.perplexity.ai" in captured["url"]
        assert captured["headers"]["Authorization"] == "Bearer pplx-abc"

    def test_user_message_included(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success()

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("구체적인 질문")

        assert captured["json"]["messages"][1]["content"] == "구체적인 질문"


# ===========================================================================
# 6. citations 파싱
# ===========================================================================

class TestParseCitations:
    def test_url_string_list(self):
        result = _parse_citations(["https://a.com", "https://b.com"])
        assert len(result) == 2
        assert result[0].url == "https://a.com"

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

    def test_empty_strings_filtered(self):
        result = _parse_citations(["", "https://a.com", "   "])
        assert len(result) == 1

    def test_none_input(self):
        assert _parse_citations(None) == []

    def test_non_list_input(self):
        assert _parse_citations("not a list") == []
        assert _parse_citations(42) == []

    def test_dict_with_link_field(self):
        result = _parse_citations([{"link": "https://a.com", "title": "A"}])
        assert len(result) == 1
        assert result[0].url == "https://a.com"

    def test_invalid_items_skipped(self):
        result = _parse_citations([
            {"url": "https://a.com"},
            None,
            123,
            {"title": "no url"},
            {"url": "https://b.com"},
        ])
        assert len(result) == 2


# ===========================================================================
# 7. 모드별 비용 계산
# ===========================================================================

class TestCalculateCostWebSearch:
    """web_search 모드 — 검색 비용 없음."""

    def _config(self):
        return _MODE_CONFIG[MODE_WEB_SEARCH]

    def test_basic_formula(self):
        # 1000 input + 500 output × $3/$15 per 1M
        cost = _calculate_cost(
            {"prompt_tokens": 1000, "completion_tokens": 500},
            self._config(),
        )
        # 0.003 + 0.0075 = 0.0105
        assert cost == pytest.approx(0.0105, abs=1e-6)

    def test_search_queries_ignored_in_web_search(self):
        """web_search 모드에서는 num_search_queries가 있어도 무시."""
        cost = _calculate_cost(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "num_search_queries": 100,  # 이거 무시됨
            },
            self._config(),
        )
        # 검색 비용 빠짐
        assert cost == pytest.approx(0.0105, abs=1e-6)


class TestCalculateCostDeepResearch:
    """deep_research 모드 — 검색 비용 포함."""

    def _config(self):
        return _MODE_CONFIG[MODE_DEEP_RESEARCH]

    def test_basic_with_searches(self):
        # 1000×$2/1M + 3000×$8/1M + 20×$5/1000
        cost = _calculate_cost(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 3000,
                "num_search_queries": 20,
            },
            self._config(),
        )
        # 0.002 + 0.024 + 0.10 = 0.126
        assert cost == pytest.approx(0.126, abs=1e-6)

    def test_no_searches_still_lower_rates(self):
        """DR에서도 토큰 단가는 낮은 (Sonar DR 쪽)."""
        cost = _calculate_cost(
            {"prompt_tokens": 1000, "completion_tokens": 1000},
            self._config(),
        )
        # 1000×2/1M + 1000×8/1M = 0.002 + 0.008 = 0.01
        assert cost == pytest.approx(0.01, abs=1e-6)


class TestCalculateCostDefensive:
    """방어적 입력 처리 (모드 무관)."""

    def _any_config(self):
        return _MODE_CONFIG[MODE_WEB_SEARCH]

    def test_zero_usage(self):
        assert _calculate_cost({}, self._any_config()) == 0.0
        assert _calculate_cost(None, self._any_config()) == 0.0

    def test_non_dict_usage(self):
        assert _calculate_cost("not dict", self._any_config()) == 0.0
        assert _calculate_cost([], self._any_config()) == 0.0

    def test_negative_tokens_clamped(self):
        cost = _calculate_cost(
            {"prompt_tokens": -100, "completion_tokens": -50},
            self._any_config(),
        )
        assert cost == 0.0

    def test_none_values(self):
        cost = _calculate_cost(
            {"prompt_tokens": None, "completion_tokens": None},
            self._any_config(),
        )
        assert cost == 0.0

    def test_string_tokens_coerced(self):
        cost = _calculate_cost(
            {"prompt_tokens": "1000", "completion_tokens": "500"},
            self._any_config(),
        )
        expected = (1000 * 3 + 500 * 15) / 1_000_000.0
        assert cost == pytest.approx(expected)


# ===========================================================================
# 8. HTTP 에러
# ===========================================================================

class TestHTTPErrors:
    def test_4xx(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_error(401)):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "401" in (result.error or "")

    def test_5xx(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_error(500)):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED

    def test_network_exception(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter()
        import httpx

        with patch(_HTTPX_PATCH, side_effect=httpx.ConnectError("refused")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "ConnectError" in (result.error or "")


# ===========================================================================
# 9. 비정상 응답
# ===========================================================================

class TestMalformedResponse:
    def test_missing_choices(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"error": "no choices"}

        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "malformed" in (result.error or "")

    def test_empty_content(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_success(content="")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "empty report" in (result.error or "")

    def test_null_content(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": None}}],
        }
        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED


# ===========================================================================
# 10. 하위호환 — PerplexityDeepResearchAdapter
# ===========================================================================

class TestBackwardCompatibility:
    def test_dr_adapter_exists(self):
        """기존 이름으로 import 가능."""
        adapter = PerplexityDeepResearchAdapter()
        assert adapter is not None

    def test_dr_adapter_uses_deep_research_mode(self):
        adapter = PerplexityDeepResearchAdapter()
        assert adapter.mode == "deep_research"
        assert adapter._config["model"] == "sonar-deep-research"

    def test_dr_adapter_preserves_legacy_name(self):
        """adapter_name이 "perplexity_sonar_dr" 로 유지돼야 (기존 DB/로그 호환)."""
        adapter = PerplexityDeepResearchAdapter()
        assert adapter.name == "perplexity_sonar_dr"

    def test_dr_adapter_long_timeout(self):
        adapter = PerplexityDeepResearchAdapter()
        assert adapter.default_timeout == 600.0

    def test_dr_adapter_research_returns_correct_name(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
        adapter = PerplexityDeepResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_success(content="ok")):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.adapter_name == "perplexity_sonar_dr"
        assert result.model == "sonar-deep-research"

    def test_dr_adapter_no_args_constructor(self):
        """하위호환: 인자 없이 생성되던 기존 코드 보호."""
        # 그냥 호출되면 OK (ValueError 안 나야)
        PerplexityDeepResearchAdapter()


# ===========================================================================
# 11. 실사용 시나리오
# ===========================================================================

class TestRealisticScenarios:
    def test_web_search_realistic(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-real")
        adapter = PerplexityResearchAdapter(mode="web_search")

        mock_resp = _mock_success(
            content="""# 커피 로스팅 기초

## 핵심 단계
1. 건조
2. 마이야르
3. 1차 크랙

참고 자료 참조.
""",
            citations=[
                "https://scaa.org/roasting",
                "https://sweetmarias.com",
            ],
            usage={
                "prompt_tokens": 80,
                "completion_tokens": 800,
            },
        )

        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("커피 로스팅 기초")

        assert result.is_success
        assert "커피 로스팅" in result.report
        assert len(result.citations) == 2
        assert result.model == "sonar-pro"
        # 80×3/1M + 800×15/1M = 0.00024 + 0.012 = 0.01224
        assert result.cost_usd == pytest.approx(0.01224, abs=1e-4)

    def test_deep_research_realistic(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-real")
        adapter = PerplexityResearchAdapter(mode="deep_research")

        mock_resp = _mock_success(
            content="# 심층 커피 로스팅 분석\n\n[수십개 소스 기반 상세 보고서]",
            citations=[f"https://source{i}.com" for i in range(15)],
            usage={
                "prompt_tokens": 150,
                "completion_tokens": 3000,
                "total_tokens": 3150,
                "num_search_queries": 28,
            },
        )

        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("커피 로스팅 심화 가이드")

        assert result.is_success
        assert len(result.citations) == 15
        assert result.model == "sonar-deep-research"
        # 150×2/1M + 3000×8/1M + 28×5/1000 = 0.0003 + 0.024 + 0.14 = 0.1643
        assert result.cost_usd == pytest.approx(0.1643, abs=1e-4)
