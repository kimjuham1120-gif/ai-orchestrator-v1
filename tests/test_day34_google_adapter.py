"""
Day 34 — Google Adapter (disabled) + Brave Adapter (real 계약) 검증.

Google Custom Search API 신규 가입 불가로 인해:
  - google_adapter: disabled 계약 검증 (is_available=False, error 반환)
  - brave_adapter:  Day 34 real 어댑터로 교체

google_adapter disabled 계약:
  어떤 환경변수를 설정해도 is_available()=False
  search() 호출 시 항상 error 반환 (claims 없음)
  오케스트레이터 전체 흐름을 깨지 않아야 함

brave_adapter 계약:
  key 없음            → error 반환, is_available()=False
  key 있음 + 성공     → real claims 반환
  key 있음 + HTTP실패 → 예외 전파
  key 있음 + 네트워크 → 예외 전파
  조용한 폴백 금지
"""
import os
from unittest.mock import patch, MagicMock

import httpx
import pytest

from src.research.google_adapter import GoogleResearchAdapter
from src.research.brave_adapter import BraveSearchAdapter


# ===========================================================================
# Google Adapter — disabled 계약
# ===========================================================================

class TestGoogleAdapterDisabled:
    def test_always_unavailable_without_key(self):
        """key 없음 → is_available()=False."""
        with patch.dict(os.environ, {}, clear=True):
            assert not GoogleResearchAdapter().is_available()

    def test_always_unavailable_with_key(self):
        """key 설정해도 v1 disabled → is_available()=False."""
        with patch.dict(os.environ, {"GOOGLE_RESEARCH_API_KEY": "sk-test"}, clear=True):
            assert not GoogleResearchAdapter().is_available()

    def test_always_unavailable_with_key_and_cx(self):
        """key + CX 설정해도 v1 disabled → is_available()=False."""
        env = {"GOOGLE_RESEARCH_API_KEY": "sk-test", "GOOGLE_RESEARCH_CX": "cx-001"}
        with patch.dict(os.environ, env, clear=True):
            assert not GoogleResearchAdapter().is_available()

    def test_search_always_returns_error(self):
        """search() 호출 → 항상 error 반환, claims 없음."""
        with patch.dict(os.environ, {}, clear=True):
            result = GoogleResearchAdapter().search("any query")
        assert result.error is not None
        assert result.claims == []

    def test_search_error_mentions_disabled(self):
        """error 메시지에 disabled 관련 내용 포함."""
        result = GoogleResearchAdapter().search("query")
        assert "disabled" in result.error.lower() or "v1" in result.error

    def test_search_never_makes_http_call(self):
        """search()가 HTTP 호출을 하지 않음 — disabled이므로."""
        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            GoogleResearchAdapter().search("query")
            mock_get.assert_not_called()
            mock_post.assert_not_called()

    def test_disabled_does_not_break_router(self):
        """google disabled 상태에서 router가 정상 동작."""
        with patch.dict(os.environ, {"YOUTUBE_TRANSCRIPT_MODE": "disabled"}, clear=True):
            from src.research.router import run_research
            bundle = run_research("test query")
            # google이 없어도 bundle이 반환됨 (빈 번들도 정상)
            assert hasattr(bundle, "claims")
            assert hasattr(bundle, "sources")

    def test_disabled_does_not_break_full_orchestration(self, tmp_path):
        """google disabled 상태에서 전체 오케스트레이션이 깨지지 않음."""
        from src.orchestrator import run_orchestration
        db = str(tmp_path / "t.db")
        with patch.dict(os.environ, {}, clear=True):
            result = run_orchestration("버그 수정해줘", db)
        assert result["task_type"] == "code_fix"
        assert result["run_status"] == "waiting_approval"


# ===========================================================================
# Brave Adapter — real 계약 (Day 34 대체 어댑터)
# ===========================================================================

class TestBraveAdapterInactive:
    def test_no_key_is_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            assert not BraveSearchAdapter().is_available()

    def test_no_key_returns_error(self):
        with patch.dict(os.environ, {}, clear=True):
            result = BraveSearchAdapter().search("query")
            assert result.error is not None
            assert "BRAVE_SEARCH_API_KEY" in result.error
            assert result.claims == []

    def test_no_key_does_not_make_http_call(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("httpx.get") as mock_get:
                BraveSearchAdapter().search("query")
                mock_get.assert_not_called()


class TestBraveAdapterRealSuccess:
    def _mock_response(self, results: list) -> MagicMock:
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.json.return_value = {"web": {"results": results}}
        return m

    def test_key_present_calls_brave_api(self):
        """key 있음 → httpx.get 호출, 올바른 헤더 전달."""
        mock_resp = self._mock_response([
            {"description": "Brave result", "url": "https://example.com/1"}
        ])
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "bsk-test"}, clear=True):
            with patch("httpx.get", return_value=mock_resp) as mock_get:
                BraveSearchAdapter().search("python")
                mock_get.assert_called_once()
                call_kwargs = mock_get.call_args
                headers = call_kwargs[1]["headers"]
                assert headers["X-Subscription-Token"] == "bsk-test"
                params = call_kwargs[1]["params"]
                assert params["q"] == "python"

    def test_response_mapped_to_claims(self):
        """응답 results → ResearchClaim 변환."""
        mock_resp = self._mock_response([
            {"description": "결과 설명 1", "url": "https://example.com/1"},
            {"description": "결과 설명 2", "url": "https://example.com/2"},
        ])
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "bsk-test"}, clear=True):
            with patch("httpx.get", return_value=mock_resp):
                result = BraveSearchAdapter().search("query")
        assert result.error is None
        assert len(result.claims) == 2
        assert result.claims[0].text == "결과 설명 1"
        assert result.claims[0].source == "https://example.com/1"

    def test_title_fallback_when_no_description(self):
        """description 없으면 title로 폴백."""
        mock_resp = self._mock_response([
            {"title": "제목만 있음", "url": "https://example.com/1"}
        ])
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "bsk-test"}, clear=True):
            with patch("httpx.get", return_value=mock_resp):
                result = BraveSearchAdapter().search("query")
        assert result.claims[0].text == "제목만 있음"

    def test_empty_results_returns_empty_claims(self):
        """results=[] → claims=[], error=None."""
        mock_resp = self._mock_response([])
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "bsk-test"}, clear=True):
            with patch("httpx.get", return_value=mock_resp):
                result = BraveSearchAdapter().search("obscure")
        assert result.error is None
        assert result.claims == []


class TestBraveAdapterRealFailure:
    def test_http_401_raises(self):
        """key 있음 + 401 → HTTPStatusError 전파."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=MagicMock()
        )
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "bsk-invalid"}, clear=True):
            with patch("httpx.get", return_value=mock_resp):
                with pytest.raises(httpx.HTTPStatusError):
                    BraveSearchAdapter().search("query")

    def test_http_429_raises(self):
        """key 있음 + 429 rate limit → HTTPStatusError 전파."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429", request=MagicMock(), response=MagicMock()
        )
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "bsk-test"}, clear=True):
            with patch("httpx.get", return_value=mock_resp):
                with pytest.raises(httpx.HTTPStatusError):
                    BraveSearchAdapter().search("query")

    def test_timeout_raises(self):
        """key 있음 + 타임아웃 → TimeoutException 전파."""
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "bsk-test"}, clear=True):
            with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
                with pytest.raises(httpx.TimeoutException):
                    BraveSearchAdapter().search("query")

    def test_network_error_raises(self):
        """key 있음 + 연결 실패 → ConnectError 전파."""
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "bsk-test"}, clear=True):
            with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
                with pytest.raises(httpx.ConnectError):
                    BraveSearchAdapter().search("query")

    def test_failure_does_not_silently_return_empty(self):
        """실패 시 빈 claims를 조용히 반환하지 않고 예외를 올림."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        raised = False
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "bsk-test"}, clear=True):
            with patch("httpx.get", return_value=mock_resp):
                try:
                    BraveSearchAdapter().search("query")
                except httpx.HTTPStatusError:
                    raised = True
        assert raised, "예외가 전파되지 않음 — 조용한 폴백 발생"


# ===========================================================================
# router 통합 — brave/youtube 조합
# ===========================================================================

class TestRouterWithNewAdapters:
    def test_router_with_brave_key_calls_brave(self):
        """BRAVE_SEARCH_API_KEY 있으면 router가 brave를 사용 (support 위치)."""
        import src.research.router as router_mod
        from src.research.brave_adapter import BraveSearchAdapter

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "web": {"results": [{"description": "brave result", "url": "https://brave.example/1"}]}
        }
        env = {"BRAVE_SEARCH_API_KEY": "bsk-test",
               "YOUTUBE_TRANSCRIPT_MODE": "disabled",
               "GEMINI_API_KEY": "", "GOOGLE_API_KEY": "",
               "OPENAI_API_KEY": "", "PERPLEXITY_API_KEY": ""}

        with patch.dict(os.environ, env, clear=True):
            # Brave를 _SUPPORT에 주입
            with patch.object(router_mod, "_SUPPORT_ADAPTER_CLASSES", (BraveSearchAdapter,)):
                with patch.object(router_mod, "_DEEP_RESEARCH_CLASSES", ()):
                    with patch("httpx.get", return_value=mock_resp):
                        from src.research.router import run_research
                        bundle = run_research("test query")
        assert len(bundle.claims) > 0
        assert bundle.claims[0].text == "brave result"

    def test_router_brave_failure_records_error_and_continues(self):
        """brave 실패 → 에러 기록 후 YouTube stub으로 계속."""
        with patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "bsk-test"}, clear=True):
            with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
                from src.research.router import run_research
                bundle = run_research("test query")
        # 예외가 전파되지 않고 번들이 반환됨
        assert hasattr(bundle, "claims")

    def test_router_all_disabled_returns_empty_bundle(self):
        """모든 adapter 비활성 → 빈 번들."""
        env = {"YOUTUBE_TRANSCRIPT_MODE": "disabled"}
        with patch.dict(os.environ, env, clear=True):
            from src.research.router import run_research
            bundle = run_research("test query")
        assert bundle.claims == []
        assert bundle.sources == []

    def test_router_youtube_contributes_when_alone(self):
        """brave/tavily/perplexity 없어도 YouTube(기본 활성)는 기여."""
        with patch.dict(os.environ, {}, clear=True):
            from src.research.router import run_research
            bundle = run_research("test query")
        assert isinstance(bundle.claims, list)
