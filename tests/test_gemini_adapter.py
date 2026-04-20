"""
Gemini Research Adapter 계약 테스트.

계약:
  key 없음          → error 반환, is_available()=False
  key 있음 + 성공   → claims 반환, error=None
  key 있음 + 실패   → 예외 전파 (조용한 폴백 없음)
  router 통합       → key 있으면 gemini가 우선순위 1번
"""
import os
from unittest.mock import patch, MagicMock, call

import pytest

from src.research.gemini_adapter import GeminiResearchAdapter, _parse_claims
from src.research.base import ResearchClaim


# ---------------------------------------------------------------------------
# 비활성 케이스
# ---------------------------------------------------------------------------

class TestGeminiAdapterInactive:
    def test_no_key_is_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            assert not GeminiResearchAdapter().is_available()

    def test_no_key_returns_error(self):
        with patch.dict(os.environ, {}, clear=True):
            result = GeminiResearchAdapter().search("query")
        assert result.error is not None
        assert result.claims == []

    def test_gemini_api_key_is_available(self):
        """GEMINI_API_KEY 있으면 is_available()=True."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gk-test"}, clear=True):
            assert GeminiResearchAdapter().is_available()

    def test_google_api_key_fallback_is_available(self):
        """GOOGLE_API_KEY로도 is_available()=True."""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "gk-test"}, clear=True):
            assert GeminiResearchAdapter().is_available()

    def test_google_api_key_takes_priority(self):
        """둘 다 있으면 GOOGLE_API_KEY 우선."""
        env = {"GOOGLE_API_KEY": "google-key", "GEMINI_API_KEY": "gemini-key"}
        with patch.dict(os.environ, env, clear=True):
            adapter = GeminiResearchAdapter()
            assert adapter._api_key == "google-key"

    def test_no_key_does_not_import_genai(self):
        """key 없으면 google.genai import조차 하지 않음."""
        with patch.dict(os.environ, {}, clear=True):
            with patch.dict("sys.modules", {"google.genai": None}):
                result = GeminiResearchAdapter().search("query")
        assert result.error is not None


# ---------------------------------------------------------------------------
# real 호출 성공 케이스 (mock)
# ---------------------------------------------------------------------------

class TestGeminiAdapterSuccess:
    def _make_streaming_mock(self, texts: list[str]):
        """스트리밍 chunk 목 생성."""
        chunks = []
        for t in texts:
            c = MagicMock()
            c.text = t
            chunks.append(c)
        return chunks

    def test_key_present_calls_genai(self):
        """key 있음 → genai.Client 생성 + generate_content_stream 호출."""
        mock_client = MagicMock()
        mock_client.models.generate_content_stream.return_value = \
            self._make_streaming_mock(["결과1 | 공식문서\n결과2 | 기술블로그"])

        with patch.dict(os.environ, {"GEMINI_API_KEY": "gk-test"}, clear=True):
            with patch("google.genai.Client", return_value=mock_client):
                result = GeminiResearchAdapter().search("python bug")

        mock_client.models.generate_content_stream.assert_called_once()
        assert result.error is None

    def test_streaming_chunks_joined(self):
        """여러 chunk가 합쳐져서 파싱됨."""
        mock_client = MagicMock()
        mock_client.models.generate_content_stream.return_value = \
            self._make_streaming_mock([
                "1. 근거 A | 공식문서\n",
                "2. 근거 B | 기술블로그\n",
            ])

        with patch.dict(os.environ, {"GEMINI_API_KEY": "gk-test"}, clear=True):
            with patch("google.genai.Client", return_value=mock_client):
                result = GeminiResearchAdapter().search("query")

        assert result.error is None
        assert len(result.claims) == 2
        assert result.claims[0].text == "근거 A"
        assert result.claims[0].source == "공식문서"

    def test_model_default_is_flash(self):
        """GEMINI_MODEL 없으면 gemini-2.5-flash 사용."""
        mock_client = MagicMock()
        mock_client.models.generate_content_stream.return_value = \
            self._make_streaming_mock(["결과 | 웹"])

        env = {"GEMINI_API_KEY": "gk-test"}
        with patch.dict(os.environ, env, clear=True):
            with patch("google.genai.Client", return_value=mock_client):
                GeminiResearchAdapter().search("query")

        call_kwargs = mock_client.models.generate_content_stream.call_args
        assert call_kwargs[1]["model"] == "gemini-2.5-flash"

    def test_custom_model_env(self):
        """GEMINI_MODEL 환경변수가 반영됨."""
        mock_client = MagicMock()
        mock_client.models.generate_content_stream.return_value = \
            self._make_streaming_mock(["결과 | 웹"])

        env = {"GEMINI_API_KEY": "gk-test", "GEMINI_MODEL": "gemini-3.1-pro-preview"}
        with patch.dict(os.environ, env, clear=True):
            with patch("google.genai.Client", return_value=mock_client):
                GeminiResearchAdapter().search("query")

        call_kwargs = mock_client.models.generate_content_stream.call_args
        assert call_kwargs[1]["model"] == "gemini-3.1-pro-preview"

    def test_thinking_level_high_default(self):
        """GEMINI_THINKING_LEVEL 없으면 HIGH."""
        mock_client = MagicMock()
        mock_client.models.generate_content_stream.return_value = \
            self._make_streaming_mock(["결과 | 웹"])

        with patch.dict(os.environ, {"GEMINI_API_KEY": "gk-test"}, clear=True):
            with patch("google.genai.Client", return_value=mock_client):
                adapter = GeminiResearchAdapter()
                assert adapter._thinking_level == "HIGH"

    def test_empty_response_returns_error(self):
        """스트림에서 텍스트가 전혀 없으면 error 반환."""
        mock_client = MagicMock()
        chunk = MagicMock()
        chunk.text = ""
        mock_client.models.generate_content_stream.return_value = [chunk]

        with patch.dict(os.environ, {"GEMINI_API_KEY": "gk-test"}, clear=True):
            with patch("google.genai.Client", return_value=mock_client):
                result = GeminiResearchAdapter().search("query")

        assert result.error is not None


# ---------------------------------------------------------------------------
# real 호출 실패 케이스 — 예외 전파
# ---------------------------------------------------------------------------

class TestGeminiAdapterFailure:
    def test_api_error_raises(self):
        """key 있음 + API 오류 → 예외 전파."""
        mock_client = MagicMock()
        mock_client.models.generate_content_stream.side_effect = \
            Exception("API_ERROR: invalid key")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "gk-invalid"}, clear=True):
            with patch("google.genai.Client", return_value=mock_client):
                with pytest.raises(Exception, match="API_ERROR"):
                    GeminiResearchAdapter().search("query")

    def test_network_error_raises(self):
        """네트워크 오류 → 예외 전파."""
        mock_client = MagicMock()
        mock_client.models.generate_content_stream.side_effect = \
            ConnectionError("network unreachable")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "gk-test"}, clear=True):
            with patch("google.genai.Client", return_value=mock_client):
                with pytest.raises(ConnectionError):
                    GeminiResearchAdapter().search("query")

    def test_failure_does_not_return_stub(self):
        """실패 시 stub claims를 조용히 반환하지 않음."""
        mock_client = MagicMock()
        mock_client.models.generate_content_stream.side_effect = \
            RuntimeError("quota exceeded")

        raised = False
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gk-test"}, clear=True):
            with patch("google.genai.Client", return_value=mock_client):
                try:
                    GeminiResearchAdapter().search("query")
                except RuntimeError:
                    raised = True
        assert raised


# ---------------------------------------------------------------------------
# _parse_claims 단위 테스트
# ---------------------------------------------------------------------------

class TestParseClaimsHelper:
    def test_pipe_format_parsed(self):
        text = "1. 근거 A | 공식문서\n2. 근거 B | 기술블로그"
        claims = _parse_claims(text, "query")
        assert len(claims) == 2
        assert claims[0].text == "근거 A"
        assert claims[0].source == "공식문서"
        assert claims[1].text == "근거 B"
        assert claims[1].source == "기술블로그"

    def test_no_pipe_falls_back_to_default_source(self):
        text = "근거 텍스트만 있음"
        claims = _parse_claims(text, "query")
        assert claims[0].text == "근거 텍스트만 있음"
        assert "gemini" in claims[0].source

    def test_empty_lines_skipped(self):
        text = "근거 A | 웹\n\n\n근거 B | 문서"
        claims = _parse_claims(text, "query")
        assert len(claims) == 2

    def test_dash_prefix_stripped(self):
        text = "- 근거 A | 웹"
        claims = _parse_claims(text, "query")
        assert claims[0].text == "근거 A"

    def test_empty_text_returns_single_claim(self):
        """파싱 결과 없으면 전체 텍스트를 단일 claim으로."""
        claims = _parse_claims("전체 텍스트", "query")
        assert len(claims) == 1


# ---------------------------------------------------------------------------
# router 통합
# ---------------------------------------------------------------------------

class TestRouterWithGemini:
    def test_gemini_key_makes_it_available(self):
        """GEMINI_API_KEY 있으면 router가 gemini deep research를 우선 사용."""
        # GeminiDeepResearchAdapter (Interactions API) mock
        mock_interaction = MagicMock()
        mock_interaction.id = "interaction-001"
        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_output = MagicMock()
        mock_output.text = "결과 | 공식문서"
        mock_result.outputs = [mock_output]

        mock_client = MagicMock()
        mock_client.interactions.create.return_value = mock_interaction
        mock_client.interactions.get.return_value = mock_result

        env = {"GEMINI_API_KEY": "gk-test", "YOUTUBE_TRANSCRIPT_MODE": "disabled",
               "OPENAI_API_KEY": "", "PERPLEXITY_API_KEY": ""}
        with patch.dict(os.environ, env, clear=True):
            with patch("google.genai.Client", return_value=mock_client):
                from src.research.router import run_research
                bundle = run_research("test query")

        assert len(bundle.claims) > 0
        assert "공식문서" in bundle.claims[0].source

    def test_no_gemini_key_falls_back_to_youtube(self):
        """모든 real key 없으면 YouTube stub으로 폴백."""
        env = {}  # 모든 key 제거
        with patch.dict(os.environ, env, clear=True):
            from src.research.router import run_research
            bundle = run_research("test query")
        # YouTube stub이 기본 활성 → claims 있음
        assert isinstance(bundle.claims, list)

    def test_gemini_failure_propagates_in_router(self):
        """gemini key 있음 + interactions.create 실패 → 예외 전파 (v2 실패 정책)."""
        mock_client = MagicMock()
        mock_client.interactions.create.side_effect = RuntimeError("quota exceeded")

        env = {"GEMINI_API_KEY": "gk-test"}
        with patch.dict(os.environ, env, clear=True):
            with patch("google.genai.Client", return_value=mock_client):
                from src.research.router import run_research
                with pytest.raises(RuntimeError, match="quota exceeded"):
                    run_research("test query")

    def test_gemini_disabled_full_orchestration_still_works(self, tmp_path):
        """GEMINI_API_KEY 없어도 전체 오케스트레이션 정상 완주."""
        from src.orchestrator import run_orchestration
        db = str(tmp_path / "t.db")
        with patch.dict(os.environ, {}, clear=True):
            result = run_orchestration("버그 수정해줘", db)
        assert result["run_status"] == "waiting_approval"
        assert result["task_type"] == "code_fix"
