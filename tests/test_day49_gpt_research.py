"""
Day 49~56 — GPT 심층리서치 포함 / Tavily 제외 테스트.

정책:
  - 실 네트워크 호출 금지 (monkeypatch / mock 전용)
  - 기존 197개 테스트에 추가되는 형태
  - artifact_store 스키마 변경 없음
"""
from __future__ import annotations

import json
import os
import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# GPT Research Adapter 테스트
# ===========================================================================

class TestGPTResearchAdapterAvailability:
    def test_no_key_is_not_available(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert GPTResearchAdapter().is_available() is False

    def test_key_present_is_available(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert GPTResearchAdapter().is_available() is True

    def test_no_key_search_returns_error(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from src.research.gpt_research_adapter import GPTResearchAdapter
        result = GPTResearchAdapter().search("test")
        assert result.error is not None
        assert "OPENAI_API_KEY" in result.error

    def test_env_override_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GPT_RESEARCH_MODEL", "gpt-4o")
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert GPTResearchAdapter()._model == "gpt-4o"

    def test_env_override_base_url(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GPT_RESEARCH_BASE_URL", "https://custom.openai.test/v1")
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert GPTResearchAdapter()._base_url == "https://custom.openai.test/v1"

    def test_env_override_timeout(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GPT_RESEARCH_TIMEOUT", "90.0")
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert GPTResearchAdapter()._timeout == 90.0

    def test_default_model_is_gpt4o_mini(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("GPT_RESEARCH_MODEL", raising=False)
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert GPTResearchAdapter()._model == "gpt-4o-mini"


class TestGPTResearchAdapterRealCall:
    def _make_mock_response(self, text: str, status_code: int = 200):
        class MockResponse:
            def __init__(self):
                self.status_code = status_code

            def raise_for_status(self):
                if self.status_code >= 400:
                    import httpx
                    raise httpx.HTTPStatusError(
                        f"HTTP {self.status_code}",
                        request=None,
                        response=self,
                    )

            def json(self):
                # Responses API 형식
                return {
                    "output": [{
                        "type": "message",
                        "content": [{
                            "type": "output_text",
                            "text": text,
                        }]
                    }]
                }

        return MockResponse()

    def test_successful_response_returns_claims(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import httpx
        mock_resp = self._make_mock_response(
            "Python async best practices | official-docs\nhttpx supports async | tech-blog"
        )
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: mock_resp)

        from src.research.gpt_research_adapter import GPTResearchAdapter
        result = GPTResearchAdapter().search("Python async")

        assert result.error is None
        assert len(result.claims) == 2
        assert result.claims[0].source == "official-docs"
        assert result.claims[1].source == "tech-blog"
        assert result.adapter_name == "gpt_research"

    def test_empty_content_returns_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import httpx

        class EmptyResp:
            def raise_for_status(self): pass
            def json(self): return {"output": []}

        monkeypatch.setattr(httpx, "post", lambda *a, **kw: EmptyResp())

        from src.research.gpt_research_adapter import GPTResearchAdapter
        result = GPTResearchAdapter().search("test")
        assert result.error is not None
        assert "비어있음" in result.error

    def test_http_error_propagates(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import httpx
        mock_resp = self._make_mock_response("", status_code=401)
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: mock_resp)

        from src.research.gpt_research_adapter import GPTResearchAdapter
        with pytest.raises(httpx.HTTPStatusError):
            GPTResearchAdapter().search("test")

    def test_network_error_propagates(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import httpx

        def raise_connect(*a, **kw):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "post", raise_connect)

        from src.research.gpt_research_adapter import GPTResearchAdapter
        with pytest.raises(httpx.ConnectError):
            GPTResearchAdapter().search("test")

    def test_timeout_propagates(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import httpx

        def raise_timeout(*a, **kw):
            raise httpx.TimeoutException("timed out")

        monkeypatch.setattr(httpx, "post", raise_timeout)

        from src.research.gpt_research_adapter import GPTResearchAdapter
        with pytest.raises(httpx.TimeoutException):
            GPTResearchAdapter().search("test")

    def test_payload_contains_web_search_tool(self, monkeypatch):
        """payload에 web_search_preview 툴 포함 확인."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-mykey")
        import httpx
        captured = {}

        def fake_post(url, headers, json, timeout):
            captured["payload"] = json
            captured["headers"] = headers
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": "result | official-docs"}
                ]}]
            }
            return resp

        monkeypatch.setattr(httpx, "post", fake_post)

        from src.research.gpt_research_adapter import GPTResearchAdapter
        GPTResearchAdapter().search("test query")

        assert captured["payload"]["tools"] == [{"type": "web_search_preview"}]
        assert "Bearer sk-mykey" in captured["headers"]["Authorization"]

    def test_numbered_lines_stripped(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import httpx
        mock_resp = self._make_mock_response(
            "1. First finding | official-docs\n2. Second finding | tech-blog"
        )
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: mock_resp)

        from src.research.gpt_research_adapter import GPTResearchAdapter
        result = GPTResearchAdapter().search("test")
        assert result.claims[0].text == "First finding"
        assert result.claims[1].text == "Second finding"

    def test_choices_fallback_format(self, monkeypatch):
        """choices 형식 응답도 파싱 가능."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import httpx

        class ChoicesResp:
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": "result | tech-blog"}}]}

        monkeypatch.setattr(httpx, "post", lambda *a, **kw: ChoicesResp())

        from src.research.gpt_research_adapter import GPTResearchAdapter
        result = GPTResearchAdapter().search("test")
        assert result.error is None
        assert len(result.claims) >= 1


class TestGPTResearchAdapterParseClaims:
    def test_pipe_separated(self):
        from src.research.gpt_research_adapter import _parse_deep_research_claims as _parse_claims
        claims = _parse_claims("finding A | official-docs\nfinding B | tech-blog", "q")
        assert len(claims) == 2
        assert claims[0].text == "finding A"
        assert claims[0].source == "official-docs"

    def test_empty_lines_skipped(self):
        from src.research.gpt_research_adapter import _parse_deep_research_claims as _parse_claims
        claims = _parse_claims("finding A | official-docs\n\n\nfinding B | community", "q")
        assert len(claims) == 2

    def test_no_pipe_fallback_source(self):
        from src.research.gpt_research_adapter import _parse_deep_research_claims as _parse_claims
        claims = _parse_claims("some finding without pipe", "q")
        assert claims[0].source == "gpt_research/web_search"

    def test_empty_text_single_fallback(self):
        from src.research.gpt_research_adapter import _parse_deep_research_claims as _parse_claims
        claims = _parse_claims("", "my query")
        assert len(claims) == 1


class TestExtractContent:
    def test_responses_api_format(self):
        from src.research.gpt_research_adapter import _extract_content
        data = {
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "result text"}]
            }]
        }
        assert _extract_content(data) == "result text"

    def test_choices_format_fallback(self):
        from src.research.gpt_research_adapter import _extract_content
        data = {"choices": [{"message": {"content": "result text"}}]}
        assert _extract_content(data) == "result text"

    def test_empty_output(self):
        from src.research.gpt_research_adapter import _extract_content
        assert _extract_content({"output": []}) == ""

    def test_non_message_type_skipped(self):
        from src.research.gpt_research_adapter import _extract_content
        data = {"output": [{"type": "web_search_call", "content": []}]}
        assert _extract_content(data) == ""


# ===========================================================================
# Tavily disabled 테스트
# ===========================================================================

class TestTavilyDisabled:
    def test_always_unavailable(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-any-key")
        from src.research.tavily_adapter import TavilyAdapter
        assert TavilyAdapter().is_available() is False

    def test_search_returns_error(self):
        from src.research.tavily_adapter import TavilyAdapter
        result = TavilyAdapter().search("any query")
        assert result.error is not None
        assert "disabled" in result.error

    def test_not_in_router_real_classes(self):
        import src.research.router as router_mod
        from src.research.tavily_adapter import TavilyAdapter
        assert TavilyAdapter not in router_mod._REAL_ADAPTER_CLASSES

    def test_not_in_router_stub_classes(self):
        import src.research.router as router_mod
        from src.research.tavily_adapter import TavilyAdapter
        assert TavilyAdapter not in router_mod._STUB_ADAPTER_CLASSES


# ===========================================================================
# Router v3 구조 테스트
# ===========================================================================

class TestRouterV3Structure:
    def test_gpt_in_real_adapter_classes(self):
        import src.research.router as router_mod
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert GPTResearchAdapter in router_mod._REAL_ADAPTER_CLASSES

    def test_gemini_deep_research_is_first(self):
        """v4 router: GeminiDeepResearchAdapter가 _DEEP_RESEARCH_CLASSES[0]."""
        import src.research.router as router_mod
        from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
        assert router_mod._DEEP_RESEARCH_CLASSES[0] is GeminiDeepResearchAdapter

    def test_gpt_is_second(self):
        """GPT가 두 번째 핵심 research 축."""
        import src.research.router as router_mod
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert router_mod._REAL_ADAPTER_CLASSES[1] is GPTResearchAdapter

    def test_stub_classes_empty(self):
        import src.research.router as router_mod
        assert len(router_mod._STUB_ADAPTER_CLASSES) == 0

    def test_gpt_key_present_calls_gpt(self, monkeypatch):
        """OPENAI_API_KEY 있으면 router가 GPT research 호출."""
        import httpx, src.research.router as router_mod

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "gpt result | official-docs"}
            ]}]
        }

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        monkeypatch.setenv("YOUTUBE_TRANSCRIPT_MODE", "disabled")
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: resp)

        bundle = router_mod.run_research("test")
        assert len(bundle.claims) == 1
        assert bundle.claims[0].text == "gpt result"

    def test_gpt_failure_propagates(self, monkeypatch):
        """GPT key 있음 + 실패 → 예외 전파."""
        import httpx, src.research.router as router_mod

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)

        def raise_err(*a, **kw):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx, "post", raise_err)

        with pytest.raises(httpx.ConnectError):
            router_mod.run_research("test")

    def test_youtube_not_called_when_real_active(self, monkeypatch):
        """real 어댑터 하나라도 활성이면 YouTube 호출 안 됨."""
        import httpx, src.research.router as router_mod
        from src.research.base import BaseResearchAdapter, ResearchResult

        yt_calls = []

        class TrackYt(BaseResearchAdapter):
            name = "youtube"
            def is_available(self): return True
            def search(self, q):
                yt_calls.append(1)
                return ResearchResult("yt", [])

        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        monkeypatch.setattr(router_mod, "_FALLBACK_ADAPTER_CLASSES", (TrackYt,))

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "result | tech-blog"}
            ]}]
        }
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: resp)

        router_mod.run_research("test")
        assert yt_calls == []
