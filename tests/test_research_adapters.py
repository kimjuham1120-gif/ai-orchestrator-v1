"""Research adapter stub/mock 테스트."""
from unittest.mock import patch

from src.research.google_adapter import GoogleResearchAdapter
from src.research.brave_adapter import BraveSearchAdapter
from src.research.perplexity_adapter import PerplexityAdapter
from src.research.youtube_adapter import YouTubeTranscriptAdapter
from src.research.router import run_research
from src.research.evidence_bundle import build_evidence_bundle


# --- google (v1 disabled) ---

def test_google_adapter_always_unavailable():
    """v1 disabled — 어떤 환경에서도 is_available()=False."""
    with patch.dict("os.environ", {}, clear=True):
        assert not GoogleResearchAdapter().is_available()

    with patch.dict("os.environ", {"GOOGLE_RESEARCH_API_KEY": "sk-test"}, clear=True):
        assert not GoogleResearchAdapter().is_available()


def test_google_adapter_search_returns_error():
    """v1 disabled — search()는 항상 error 반환."""
    result = GoogleResearchAdapter().search("test query")
    assert result.error is not None
    assert result.claims == []


# --- brave ---

def test_brave_adapter_unavailable_without_key():
    with patch.dict("os.environ", {}, clear=True):
        adapter = BraveSearchAdapter()
        assert not adapter.is_available()
        result = adapter.search("test query")
        assert result.error is not None


# --- perplexity ---

def test_perplexity_adapter_unavailable():
    with patch.dict("os.environ", {}, clear=True):
        adapter = PerplexityAdapter()
        assert not adapter.is_available()


def test_perplexity_adapter_real_with_mock():
    """key 있음 → real 호출 경로. httpx mock으로 네트워크 없이 검증."""
    import json
    from unittest.mock import MagicMock
    payload = json.dumps({
        "choices": [{"message": {"content": "finding A | official-docs\nfinding B | tech-blog"}}]
    })
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = json.loads(payload)

    with patch.dict("os.environ", {"PERPLEXITY_API_KEY": "test-key"}):
        import httpx
        with patch.object(httpx, "post", return_value=mock_resp):
            adapter = PerplexityAdapter()
            result = adapter.search("test")
            assert len(result.claims) > 0


# --- youtube ---

def test_youtube_adapter_default_available():
    """YOUTUBE_TRANSCRIPT_MODE 기본값은 manual → available."""
    with patch.dict("os.environ", {}, clear=True):
        adapter = YouTubeTranscriptAdapter()
        assert adapter.is_available()


def test_youtube_adapter_disabled():
    with patch.dict("os.environ", {"YOUTUBE_TRANSCRIPT_MODE": "disabled"}):
        adapter = YouTubeTranscriptAdapter()
        assert not adapter.is_available()


# --- evidence bundle ---

def test_evidence_bundle_deduplication():
    from src.research.base import ResearchResult, ResearchClaim
    r1 = ResearchResult("a", claims=[ResearchClaim("claim1", "src1")])
    r2 = ResearchResult("b", claims=[ResearchClaim("claim1", "src1"), ResearchClaim("claim2", "src2")])
    bundle = build_evidence_bundle([r1, r2])
    assert len(bundle.claims) == 2  # 중복 제거


def test_run_research_returns_bundle():
    with patch.dict("os.environ", {}, clear=True):
        bundle = run_research("test query")
        assert hasattr(bundle, "claims")
        assert hasattr(bundle, "sources")
