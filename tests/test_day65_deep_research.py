"""
Day 65~72 — GPT + Gemini 심층리서치 장착 테스트.

정책:
  - 실 네트워크 호출 금지 (monkeypatch / mock 전용)
  - 기존 254개 테스트에 추가
  - artifact_store 스키마 변경 없음
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# GPT Deep Research Adapter 보강 테스트
# ===========================================================================

class TestGPTDeepResearchAdapter:
    def _make_responses_mock(self, text: str, status_code: int = 200):
        class MockResp:
            def raise_for_status(self):
                if status_code >= 400:
                    import httpx
                    raise httpx.HTTPStatusError(
                        f"HTTP {status_code}", request=None, response=self
                    )
            def json(self):
                return {"output": [{"type": "message", "content": [
                    {"type": "output_text", "text": text}
                ]}]}
        return MockResp()

    def test_no_key_not_available(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert GPTResearchAdapter().is_available() is False

    def test_key_present_available(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert GPTResearchAdapter().is_available() is True

    def test_deep_research_model_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GPT_RESEARCH_MODEL", "openai/o4-mini-deep-research")
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert GPTResearchAdapter()._model == "openai/o4-mini-deep-research"

    def test_timeout_default_120(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("GPT_RESEARCH_TIMEOUT", raising=False)
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert GPTResearchAdapter()._timeout == 120.0

    def test_three_part_claim_parsed(self, monkeypatch):
        """finding | source | confidence 형식 파싱."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import httpx
        mock_resp = self._make_responses_mock(
            "Python asyncio is event-loop based | official-docs | confidence: high\n"
            "httpx supports async | tech-blog | confidence: medium"
        )
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: mock_resp)

        from src.research.gpt_research_adapter import GPTResearchAdapter
        result = GPTResearchAdapter().search("Python async")
        assert result.error is None
        assert len(result.claims) == 2
        assert "high" in result.claims[0].source
        assert "medium" in result.claims[1].source

    def test_two_part_claim_parsed(self, monkeypatch):
        """finding | source 형식 파싱."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import httpx
        mock_resp = self._make_responses_mock("finding A | official-docs")
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: mock_resp)

        from src.research.gpt_research_adapter import GPTResearchAdapter
        result = GPTResearchAdapter().search("test")
        assert result.claims[0].source == "official-docs"

    def test_http_error_propagates(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import httpx
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: self._make_responses_mock("", 401))
        from src.research.gpt_research_adapter import GPTResearchAdapter
        with pytest.raises(httpx.HTTPStatusError):
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

    def test_empty_response_returns_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import httpx
        class EmptyResp:
            def raise_for_status(self): pass
            def json(self): return {"output": []}
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: EmptyResp())
        from src.research.gpt_research_adapter import GPTResearchAdapter
        result = GPTResearchAdapter().search("test")
        assert result.error is not None

    def test_prompt_contains_deep_research_instruction(self, monkeypatch):
        """프롬프트가 심층리서치 목적으로 구성됨을 확인."""
        from src.research.gpt_research_adapter import _DEEP_RESEARCH_PROMPT
        assert "deep research" in _DEEP_RESEARCH_PROMPT.lower() or \
               "심층" in _DEEP_RESEARCH_PROMPT or \
               "authoritative" in _DEEP_RESEARCH_PROMPT


# ===========================================================================
# Gemini Deep Research Adapter 테스트
# ===========================================================================

class TestGeminiDeepResearchAdapter:
    def test_no_key_not_available(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
        assert GeminiDeepResearchAdapter().is_available() is False

    def test_gemini_key_available(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
        from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
        assert GeminiDeepResearchAdapter().is_available() is True

    def test_google_api_key_available(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "gk-test")
        from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
        assert GeminiDeepResearchAdapter().is_available() is True

    def test_env_override_agent(self, monkeypatch):
        """GEMINI_DEEP_RESEARCH_AGENT env override 확인."""
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
        monkeypatch.setenv("GEMINI_DEEP_RESEARCH_AGENT", "deep-research-custom")
        from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
        assert GeminiDeepResearchAdapter()._agent == "deep-research-custom"

    def test_env_override_timeout(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
        monkeypatch.setenv("GEMINI_DEEP_RESEARCH_TIMEOUT", "600.0")
        from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
        assert GeminiDeepResearchAdapter()._timeout == 600.0

    def test_env_override_poll_interval(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
        monkeypatch.setenv("GEMINI_DEEP_RESEARCH_POLL_INTERVAL", "10.0")
        from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
        assert GeminiDeepResearchAdapter()._poll_interval == 10.0

    def test_successful_research_returns_claims(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")

        # Interactions API mock
        mock_interaction = MagicMock()
        mock_interaction.id = "interaction-001"

        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_output = MagicMock()
        mock_output.text = "Python 비동기 처리 | 공식문서 | 높음\nasyncio 이벤트 루프 | 기술블로그 | 중간"
        mock_result.outputs = [mock_output]

        mock_client = MagicMock()
        mock_client.interactions.create.return_value = mock_interaction
        mock_client.interactions.get.return_value = mock_result

        with patch("google.genai.Client", return_value=mock_client):
            from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
            result = GeminiDeepResearchAdapter().search("Python async")

        assert result.error is None
        assert len(result.claims) == 2
        assert result.adapter_name == "gemini_deep_research"

    def test_api_error_propagates(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
        mock_client = MagicMock()
        mock_client.interactions.create.side_effect = \
            RuntimeError("API quota exceeded")

        with patch("google.genai.Client", return_value=mock_client):
            from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
            with pytest.raises(RuntimeError, match="API quota exceeded"):
                GeminiDeepResearchAdapter().search("test")

    def test_timeout_raises(self, monkeypatch):
        """polling 중 timeout 발생 시 TimeoutError 전파."""
        import time
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
        monkeypatch.setenv("GEMINI_DEEP_RESEARCH_TIMEOUT", "0.01")
        monkeypatch.setenv("GEMINI_DEEP_RESEARCH_POLL_INTERVAL", "0.001")

        mock_interaction = MagicMock()
        mock_interaction.id = "interaction-slow"

        mock_pending = MagicMock()
        mock_pending.status = "pending"

        mock_client = MagicMock()
        mock_client.interactions.create.return_value = mock_interaction
        mock_client.interactions.get.return_value = mock_pending

        with patch("google.genai.Client", return_value=mock_client):
            from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
            with pytest.raises(TimeoutError):
                GeminiDeepResearchAdapter().search("test")

    def test_empty_response_returns_error(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")

        mock_interaction = MagicMock()
        mock_interaction.id = "interaction-empty"

        mock_result = MagicMock()
        mock_result.status = "completed"
        # outputs[-1].text가 빈 문자열
        mock_output = MagicMock()
        mock_output.text = ""
        mock_result.outputs = [mock_output]
        mock_result.output = None

        mock_client = MagicMock()
        mock_client.interactions.create.return_value = mock_interaction
        mock_client.interactions.get.return_value = mock_result

        with patch("google.genai.Client", return_value=mock_client):
            from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
            result = GeminiDeepResearchAdapter().search("test")

        assert result.error is not None

    def test_three_part_claim_parsed(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")

        mock_interaction = MagicMock()
        mock_interaction.id = "interaction-three"
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_output = MagicMock()
        mock_output.text = "asyncio 공식 지원 | 공식문서 | 높음\ncontextvar 활용 | 기술블로그 | 중간"
        mock_result.outputs = [mock_output]

        mock_client = MagicMock()
        mock_client.interactions.create.return_value = mock_interaction
        mock_client.interactions.get.return_value = mock_result

        with patch("google.genai.Client", return_value=mock_client):
            from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
            result = GeminiDeepResearchAdapter().search("Python")

        assert len(result.claims) == 2
        assert "high" in result.claims[0].source or "높음" in result.claims[0].source


    def test_failed_status_raises(self, monkeypatch):
        """status=failed → RuntimeError 전파."""
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")

        mock_interaction = MagicMock()
        mock_interaction.id = "interaction-fail"
        mock_result = MagicMock()
        mock_result.status = "failed"
        mock_result.error = "deep research failed"

        mock_client = MagicMock()
        mock_client.interactions.create.return_value = mock_interaction
        mock_client.interactions.get.return_value = mock_result

        with patch("google.genai.Client", return_value=mock_client):
            from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
            with pytest.raises(RuntimeError, match="실패"):
                GeminiDeepResearchAdapter().search("test")

    def test_agent_env_override(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
        monkeypatch.setenv("GEMINI_DEEP_RESEARCH_AGENT", "deep-research-custom")
        from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
        assert GeminiDeepResearchAdapter()._agent == "deep-research-custom"


class TestGeminiDeepResearchParseClaims:
    def test_pipe_three_part(self):
        from src.research.gemini_deep_research_adapter import _parse_claims
        claims = _parse_claims("근거 A | 공식문서 | 높음\n근거 B | 기술블로그 | 중간", "q")
        assert len(claims) == 2
        assert "high" in claims[0].source or "높음" in claims[0].source

    def test_pipe_two_part(self):
        from src.research.gemini_deep_research_adapter import _parse_claims
        claims = _parse_claims("근거 A | 공식문서", "q")
        assert claims[0].source == "공식문서"

    def test_empty_lines_skipped(self):
        from src.research.gemini_deep_research_adapter import _parse_claims
        claims = _parse_claims("근거 A | 공식문서\n\n\n근거 B | 기술블로그", "q")
        assert len(claims) == 2

    def test_empty_text_fallback(self):
        from src.research.gemini_deep_research_adapter import _parse_claims
        claims = _parse_claims("", "my query")
        assert len(claims) == 1


# ===========================================================================
# Router v4 구조 테스트
# ===========================================================================

class TestRouterV4Structure:
    def test_gemini_deep_research_is_first(self):
        import src.research.router as router_mod
        from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
        assert router_mod._DEEP_RESEARCH_CLASSES[0] is GeminiDeepResearchAdapter

    def test_gpt_research_is_second(self):
        import src.research.router as router_mod
        from src.research.gpt_research_adapter import GPTResearchAdapter
        assert router_mod._DEEP_RESEARCH_CLASSES[1] is GPTResearchAdapter

    def test_perplexity_in_support(self):
        import src.research.router as router_mod
        from src.research.perplexity_adapter import PerplexityAdapter
        assert PerplexityAdapter in router_mod._SUPPORT_ADAPTER_CLASSES

    def test_gemini_grounding_in_support(self):
        """일반 Gemini(grounding)는 support 위치."""
        import src.research.router as router_mod
        from src.research.gemini_adapter import GeminiResearchAdapter
        assert GeminiResearchAdapter in router_mod._SUPPORT_ADAPTER_CLASSES

    def test_youtube_in_fallback(self):
        import src.research.router as router_mod
        from src.research.youtube_adapter import YouTubeTranscriptAdapter
        assert YouTubeTranscriptAdapter in router_mod._FALLBACK_ADAPTER_CLASSES

    def test_stub_classes_empty(self):
        import src.research.router as router_mod
        assert len(router_mod._STUB_ADAPTER_CLASSES) == 0

    def test_real_adapter_classes_alias(self):
        """기존 테스트 호환용 _REAL_ADAPTER_CLASSES 존재 확인."""
        import src.research.router as router_mod
        assert hasattr(router_mod, "_REAL_ADAPTER_CLASSES")

    def test_deep_research_failure_propagates(self, monkeypatch):
        """deep research 어댑터 실패 → 예외 전파."""
        import src.research.router as router_mod
        from src.research.base import BaseResearchAdapter

        class FailDeep(BaseResearchAdapter):
            name = "fail_deep"
            def is_available(self): return True
            def search(self, q): raise RuntimeError("deep research failed")

        class InactiveGPT(BaseResearchAdapter):
            name = "gpt"
            def is_available(self): return False
            def search(self, q): pass

        monkeypatch.setattr(router_mod, "_DEEP_RESEARCH_CLASSES", (FailDeep, InactiveGPT))
        monkeypatch.setattr(router_mod, "_SUPPORT_ADAPTER_CLASSES", ())
        monkeypatch.setattr(router_mod, "_FALLBACK_ADAPTER_CLASSES", ())

        with pytest.raises(RuntimeError, match="deep research failed"):
            router_mod.run_research("test")

    def test_youtube_not_called_when_deep_active(self, monkeypatch):
        """deep research 활성 → YouTube 호출 안 됨."""
        import src.research.router as router_mod
        from src.research.base import BaseResearchAdapter, ResearchResult, ResearchClaim

        yt_calls = []

        class ActiveDeep(BaseResearchAdapter):
            name = "deep"
            def is_available(self): return True
            def search(self, q):
                return ResearchResult("deep", [ResearchClaim("result", "deep")])

        class TrackYT(BaseResearchAdapter):
            name = "yt"
            def is_available(self): return True
            def search(self, q): yt_calls.append(1); return ResearchResult("yt", [])

        monkeypatch.setattr(router_mod, "_DEEP_RESEARCH_CLASSES", (ActiveDeep,))
        monkeypatch.setattr(router_mod, "_SUPPORT_ADAPTER_CLASSES", ())
        monkeypatch.setattr(router_mod, "_FALLBACK_ADAPTER_CLASSES", (TrackYT,))

        router_mod.run_research("test")
        assert yt_calls == []

    def test_youtube_called_when_all_inactive(self, monkeypatch):
        """핵심+support 전원 비활성 → YouTube fallback 실행."""
        import src.research.router as router_mod
        from src.research.base import BaseResearchAdapter, ResearchResult, ResearchClaim

        yt_calls = []

        class InactiveDeep(BaseResearchAdapter):
            name = "d"
            def is_available(self): return False
            def search(self, q): pass

        class TrackYT(BaseResearchAdapter):
            name = "yt"
            def is_available(self): return True
            def search(self, q):
                yt_calls.append(1)
                return ResearchResult("yt", [ResearchClaim("yt result", "yt")])

        monkeypatch.setattr(router_mod, "_DEEP_RESEARCH_CLASSES", (InactiveDeep,))
        monkeypatch.setattr(router_mod, "_SUPPORT_ADAPTER_CLASSES", ())
        monkeypatch.setattr(router_mod, "_FALLBACK_ADAPTER_CLASSES", (TrackYT,))

        bundle = router_mod.run_research("test")
        assert yt_calls == [1]
        assert len(bundle.claims) == 1


# ===========================================================================
# YouTube support 역할 명확화 테스트
# ===========================================================================

class TestYouTubeSupportRole:
    def test_youtube_in_fallback_not_real(self):
        """YouTube는 _REAL_ADAPTER_CLASSES가 아닌 _FALLBACK에 위치."""
        import src.research.router as router_mod
        from src.research.youtube_adapter import YouTubeTranscriptAdapter
        assert YouTubeTranscriptAdapter not in router_mod._REAL_ADAPTER_CLASSES
        assert YouTubeTranscriptAdapter in router_mod._FALLBACK_ADAPTER_CLASSES

    def test_youtube_default_available(self, monkeypatch):
        """YOUTUBE_TRANSCRIPT_MODE 기본값 → available (stub 활성)."""
        monkeypatch.delenv("YOUTUBE_TRANSCRIPT_MODE", raising=False)
        from src.research.youtube_adapter import YouTubeTranscriptAdapter
        assert YouTubeTranscriptAdapter().is_available() is True

    def test_youtube_disabled_mode(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_TRANSCRIPT_MODE", "disabled")
        from src.research.youtube_adapter import YouTubeTranscriptAdapter
        assert YouTubeTranscriptAdapter().is_available() is False
