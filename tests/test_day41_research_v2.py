"""
Day 41~48 — Research 계층 v2 테스트.

정책:
  - 실 네트워크 호출 금지 (monkeypatch / mock 전용)
  - 기존 172개 테스트에 추가되는 형태
  - artifact_store 스키마 변경 없음
"""
from __future__ import annotations

import os
import pytest


# ===========================================================================
# Perplexity Adapter 테스트
# ===========================================================================

class TestPerplexityAdapterAvailability:
    def test_no_key_is_not_available(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        from src.research.perplexity_adapter import PerplexityAdapter
        adapter = PerplexityAdapter()
        assert adapter.is_available() is False

    def test_key_present_is_available(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
        from src.research.perplexity_adapter import PerplexityAdapter
        adapter = PerplexityAdapter()
        assert adapter.is_available() is True

    def test_no_key_search_returns_error_result(self, monkeypatch):
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        from src.research.perplexity_adapter import PerplexityAdapter
        adapter = PerplexityAdapter()
        result = adapter.search("test query")
        assert result.error is not None
        assert "PERPLEXITY_API_KEY" in result.error

    def test_env_override_model(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        monkeypatch.setenv("PERPLEXITY_MODEL", "sonar-pro")
        from src.research.perplexity_adapter import PerplexityAdapter
        adapter = PerplexityAdapter()
        assert adapter._model == "sonar-pro"

    def test_env_override_base_url(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        monkeypatch.setenv("PERPLEXITY_BASE_URL", "https://custom.api.test")
        from src.research.perplexity_adapter import PerplexityAdapter
        adapter = PerplexityAdapter()
        assert adapter._base_url == "https://custom.api.test"

    def test_env_override_timeout(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        monkeypatch.setenv("PERPLEXITY_TIMEOUT", "60.0")
        from src.research.perplexity_adapter import PerplexityAdapter
        adapter = PerplexityAdapter()
        assert adapter._timeout == 60.0


class TestPerplexityAdapterRealCall:
    """httpx를 mock해서 real 호출 경로 검증 (네트워크 미사용)."""

    def _make_mock_response(self, content: str, status_code: int = 200):
        """httpx.Response를 흉내내는 mock 객체."""
        import json

        class MockResponse:
            def __init__(self):
                self.status_code = status_code
                self._content = content

            def raise_for_status(self):
                if self.status_code >= 400:
                    import httpx
                    raise httpx.HTTPStatusError(
                        message=f"HTTP {self.status_code}",
                        request=None,
                        response=self,
                    )

            def json(self):
                return json.loads(self._content)

        return MockResponse()

    def test_successful_response_returns_claims(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        import json

        payload = json.dumps({
            "choices": [{
                "message": {
                    "content": "Python asyncio 공식 문서 기반 | official-docs\nhttpx는 async 지원 | tech-blog"
                }
            }]
        })
        mock_resp = self._make_mock_response(payload)

        import httpx
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: mock_resp)

        from src.research.perplexity_adapter import PerplexityAdapter
        adapter = PerplexityAdapter()
        result = adapter.search("Python async")

        assert result.error is None
        assert len(result.claims) == 2
        assert result.claims[0].source == "official-docs"
        assert result.claims[1].source == "tech-blog"
        assert result.adapter_name == "perplexity"

    def test_empty_content_returns_error(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        import json, httpx

        payload = json.dumps({"choices": [{"message": {"content": ""}}]})
        mock_resp = self._make_mock_response(payload)
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: mock_resp)

        from src.research.perplexity_adapter import PerplexityAdapter
        result = PerplexityAdapter().search("test")
        assert result.error is not None
        assert "비어있음" in result.error

    def test_http_error_propagates(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        import httpx

        mock_resp = self._make_mock_response("{}", status_code=401)
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: mock_resp)

        from src.research.perplexity_adapter import PerplexityAdapter
        with pytest.raises(httpx.HTTPStatusError):
            PerplexityAdapter().search("test")

    def test_network_error_propagates(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        import httpx

        def raise_connect(*a, **kw):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "post", raise_connect)

        from src.research.perplexity_adapter import PerplexityAdapter
        with pytest.raises(httpx.ConnectError):
            PerplexityAdapter().search("test")

    def test_timeout_propagates(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        import httpx

        def raise_timeout(*a, **kw):
            raise httpx.TimeoutException("timed out")

        monkeypatch.setattr(httpx, "post", raise_timeout)

        from src.research.perplexity_adapter import PerplexityAdapter
        with pytest.raises(httpx.TimeoutException):
            PerplexityAdapter().search("test")

    def test_claims_fallback_no_pipe(self, monkeypatch):
        """파이프 없는 응답도 단일 claim으로 파싱된다."""
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        import json, httpx

        payload = json.dumps({
            "choices": [{"message": {"content": "Some useful finding without pipe"}}]
        })
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: self._make_mock_response(payload))

        from src.research.perplexity_adapter import PerplexityAdapter
        result = PerplexityAdapter().search("test")
        assert result.error is None
        assert len(result.claims) >= 1
        assert "perplexity/sonar" in result.claims[0].source

    def test_numbered_lines_stripped(self, monkeypatch):
        """번호 접두어가 제거되고 텍스트만 claim에 남는다."""
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test")
        import json, httpx

        payload = json.dumps({
            "choices": [{"message": {"content": "1. First finding | official-docs\n2. Second finding | tech-blog"}}]
        })
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: self._make_mock_response(payload))

        from src.research.perplexity_adapter import PerplexityAdapter
        result = PerplexityAdapter().search("test")
        assert result.error is None
        assert result.claims[0].text == "First finding"
        assert result.claims[1].text == "Second finding"


class TestPerplexityAdapterClaims:
    """_parse_claims 단위 테스트."""

    def test_pipe_separated(self):
        from src.research.perplexity_adapter import _parse_claims
        claims = _parse_claims("finding A | official-docs\nfinding B | tech-blog", "q")
        assert len(claims) == 2
        assert claims[0].text == "finding A"
        assert claims[0].source == "official-docs"

    def test_empty_lines_skipped(self):
        from src.research.perplexity_adapter import _parse_claims
        claims = _parse_claims("finding A | official-docs\n\n\nfinding B | community", "q")
        assert len(claims) == 2

    def test_empty_text_fallback(self):
        from src.research.perplexity_adapter import _parse_claims
        claims = _parse_claims("", "my query")
        # 빈 텍스트 → 전체를 단일 claim
        assert len(claims) == 1


# ===========================================================================
# Router 정책 테스트 (v2)
# ===========================================================================

class TestRouterPolicyV2:
    """run_research() 실패 정책 검증."""

    def _make_adapter(self, name: str, available: bool, raises=None, result=None):
        """테스트용 더미 어댑터 팩토리."""
        from src.research.base import BaseResearchAdapter, ResearchResult, ResearchClaim

        class DummyAdapter(BaseResearchAdapter):
            pass

        DummyAdapter.name = name

        def is_available_fn(self):
            return available

        def search_fn(self, query):
            if raises:
                raise raises
            if result is not None:
                return result
            return ResearchResult(
                adapter_name=name,
                claims=[ResearchClaim(text=f"{name} result", source=name)],
            )

        DummyAdapter.is_available = is_available_fn
        DummyAdapter.search = search_fn
        return DummyAdapter

    def test_inactive_adapter_skipped(self, monkeypatch):
        """is_available=False 어댑터는 search() 호출 안 함."""
        from src.research.base import ResearchResult, ResearchClaim

        called = []

        GeminiCls = self._make_adapter("gemini", available=False)
        BraveCls = self._make_adapter("brave", available=False)
        PerplexityCls = self._make_adapter("perplexity", available=False)
        TavilyCls = self._make_adapter("tavily", available=False)

        from src.research.base import BaseResearchAdapter

        class YouTubeCls(BaseResearchAdapter):
            name = "youtube"
            def is_available(self): return True
            def search(self, q):
                called.append("youtube")
                return ResearchResult(
                    adapter_name="youtube",
                    claims=[ResearchClaim(text="yt result", source="youtube")],
                )

        import src.research.router as router_mod
        monkeypatch.setattr(router_mod, "_DEEP_RESEARCH_CLASSES", (GeminiCls, BraveCls, PerplexityCls))
        monkeypatch.setattr(router_mod, "_SUPPORT_ADAPTER_CLASSES", ())
        monkeypatch.setattr(router_mod, "_STUB_ADAPTER_CLASSES", (TavilyCls,))
        monkeypatch.setattr(router_mod, "_FALLBACK_ADAPTER_CLASSES", (YouTubeCls,))

        bundle = router_mod.run_research("test query")
        assert "youtube" in called
        assert len(bundle.claims) >= 1

    def test_real_adapter_failure_propagates(self, monkeypatch):
        """is_available=True인 real 어댑터 실패 → 예외 전파."""

        GeminiCls = self._make_adapter(
            "gemini", available=True, raises=RuntimeError("api error")
        )
        BraveCls = self._make_adapter("brave", available=False)
        PerplexityCls = self._make_adapter("perplexity", available=False)
        TavilyCls = self._make_adapter("tavily", available=False)
        YouTubeCls = self._make_adapter("youtube", available=True)

        import src.research.router as router_mod
        monkeypatch.setattr(router_mod, "_DEEP_RESEARCH_CLASSES", (GeminiCls, BraveCls, PerplexityCls))
        monkeypatch.setattr(router_mod, "_SUPPORT_ADAPTER_CLASSES", ())
        monkeypatch.setattr(router_mod, "_STUB_ADAPTER_CLASSES", (TavilyCls,))
        monkeypatch.setattr(router_mod, "_FALLBACK_ADAPTER_CLASSES", (YouTubeCls,))

        with pytest.raises(RuntimeError, match="api error"):
            router_mod.run_research("test")

    def test_youtube_not_called_when_real_active(self, monkeypatch):
        """real 어댑터가 하나라도 활성이면 YouTube는 호출 안 됨."""
        from src.research.base import ResearchResult, ResearchClaim

        youtube_called = []

        GeminiCls = self._make_adapter("gemini", available=True)
        BraveCls = self._make_adapter("brave", available=False)
        PerplexityCls = self._make_adapter("perplexity", available=False)
        TavilyCls = self._make_adapter("tavily", available=False)

        from src.research.base import BaseResearchAdapter

        class YouTubeCls(BaseResearchAdapter):
            name = "youtube"
            def is_available(self): return True
            def search(self, q):
                youtube_called.append(True)
                return ResearchResult(adapter_name="youtube", claims=[])

        import src.research.router as router_mod
        monkeypatch.setattr(router_mod, "_DEEP_RESEARCH_CLASSES", (GeminiCls, BraveCls, PerplexityCls))
        monkeypatch.setattr(router_mod, "_SUPPORT_ADAPTER_CLASSES", ())
        monkeypatch.setattr(router_mod, "_STUB_ADAPTER_CLASSES", (TavilyCls,))
        monkeypatch.setattr(router_mod, "_FALLBACK_ADAPTER_CLASSES", (YouTubeCls,))

        router_mod.run_research("test")
        assert youtube_called == [], "YouTube는 real 어댑터 활성 시 호출 안 됨"

    def test_multiple_real_adapters_results_merged(self, monkeypatch):
        """활성 real 어댑터 여럿 → 결과가 번들에 합산된다."""
        from src.research.base import ResearchResult, ResearchClaim

        GeminiCls = self._make_adapter("gemini", available=True)
        BraveCls = self._make_adapter("brave", available=True)
        PerplexityCls = self._make_adapter("perplexity", available=True)
        TavilyCls = self._make_adapter("tavily", available=False)
        YouTubeCls = self._make_adapter("youtube", available=True)

        import src.research.router as router_mod
        monkeypatch.setattr(router_mod, "_DEEP_RESEARCH_CLASSES", (GeminiCls, BraveCls, PerplexityCls))
        monkeypatch.setattr(router_mod, "_SUPPORT_ADAPTER_CLASSES", ())
        monkeypatch.setattr(router_mod, "_STUB_ADAPTER_CLASSES", (TavilyCls,))
        monkeypatch.setattr(router_mod, "_FALLBACK_ADAPTER_CLASSES", (YouTubeCls,))

        bundle = router_mod.run_research("test")
        # 3개 real 어댑터 각 1 claim
        assert len(bundle.claims) == 3

    def test_stub_adapter_failure_propagates(self, monkeypatch):
        """support 어댑터도 is_available=True면 실패 시 예외 전파."""
        GeminiCls = self._make_adapter("gemini", available=False)
        BraveCls = self._make_adapter("brave", available=False)
        PerplexityCls = self._make_adapter("perplexity", available=False)
        SupportFailCls = self._make_adapter(
            "support_fail", available=True, raises=ValueError("tavily broken")
        )
        YouTubeCls = self._make_adapter("youtube", available=True)

        import src.research.router as router_mod
        monkeypatch.setattr(router_mod, "_DEEP_RESEARCH_CLASSES", (GeminiCls, BraveCls, PerplexityCls))
        monkeypatch.setattr(router_mod, "_SUPPORT_ADAPTER_CLASSES", (SupportFailCls,))
        monkeypatch.setattr(router_mod, "_FALLBACK_ADAPTER_CLASSES", (YouTubeCls,))

        with pytest.raises(ValueError, match="tavily broken"):
            router_mod.run_research("test")

    def test_all_inactive_returns_empty_bundle(self, monkeypatch):
        """모든 어댑터 비활성 + YouTube도 비활성 → 빈 번들."""
        GeminiCls = self._make_adapter("gemini", available=False)
        BraveCls = self._make_adapter("brave", available=False)
        PerplexityCls = self._make_adapter("perplexity", available=False)
        TavilyCls = self._make_adapter("tavily", available=False)
        YouTubeCls = self._make_adapter("youtube", available=False)

        import src.research.router as router_mod
        monkeypatch.setattr(router_mod, "_DEEP_RESEARCH_CLASSES", (GeminiCls, BraveCls, PerplexityCls))
        monkeypatch.setattr(router_mod, "_SUPPORT_ADAPTER_CLASSES", ())
        monkeypatch.setattr(router_mod, "_STUB_ADAPTER_CLASSES", (TavilyCls,))
        monkeypatch.setattr(router_mod, "_FALLBACK_ADAPTER_CLASSES", (YouTubeCls,))

        bundle = router_mod.run_research("test")
        assert bundle.claims == []

    def test_youtube_failure_silenced(self, monkeypatch):
        """YouTube fallback 실패는 무시되고 빈 번들 반환."""
        GeminiCls = self._make_adapter("gemini", available=False)
        BraveCls = self._make_adapter("brave", available=False)
        PerplexityCls = self._make_adapter("perplexity", available=False)
        TavilyCls = self._make_adapter("tavily", available=False)
        YouTubeCls = self._make_adapter(
            "youtube", available=True, raises=ConnectionError("yt down")
        )

        import src.research.router as router_mod
        monkeypatch.setattr(router_mod, "_DEEP_RESEARCH_CLASSES", (GeminiCls, BraveCls, PerplexityCls))
        monkeypatch.setattr(router_mod, "_SUPPORT_ADAPTER_CLASSES", ())
        monkeypatch.setattr(router_mod, "_STUB_ADAPTER_CLASSES", (TavilyCls,))
        monkeypatch.setattr(router_mod, "_FALLBACK_ADAPTER_CLASSES", (YouTubeCls,))

        # 예외 전파 없이 빈 번들
        bundle = router_mod.run_research("test")
        assert bundle.claims == []

    def test_perplexity_in_real_adapter_classes(self, monkeypatch):
        """PerplexityAdapter가 _REAL_ADAPTER_CLASSES에 포함되어 있다."""
        import src.research.router as router_mod
        from src.research.perplexity_adapter import PerplexityAdapter
        assert PerplexityAdapter in router_mod._REAL_ADAPTER_CLASSES

    def test_gemini_is_first_real_adapter(self, monkeypatch):
        """GeminiDeepResearchAdapter가 _DEEP_RESEARCH_CLASSES[0] — primary 우선순위."""
        import src.research.router as router_mod
        from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
        assert router_mod._DEEP_RESEARCH_CLASSES[0] is GeminiDeepResearchAdapter
