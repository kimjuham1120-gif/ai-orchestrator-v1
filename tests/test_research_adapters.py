"""Research adapter stub/mock 테스트."""
from unittest.mock import patch

from src.research.google_adapter import GoogleResearchAdapter
from src.research.perplexity_adapter import PerplexityAdapter
from src.research.youtube_adapter import YouTubeTranscriptAdapter
from src.research.router import run_research
from src.research.evidence_bundle import build_evidence_bundle


def test_google_adapter_unavailable_without_key():
    with patch.dict("os.environ", {}, clear=True):
        adapter = GoogleResearchAdapter()
        assert not adapter.is_available()
        result = adapter.search("test query")
        assert result.error is not None


def test_google_adapter_stub_with_key():
    with patch.dict("os.environ", {"GOOGLE_RESEARCH_API_KEY": "test-key"}):
        adapter = GoogleResearchAdapter()
        assert adapter.is_available()
        result = adapter.search("test query")
        assert len(result.claims) > 0
        assert result.error is None


def test_perplexity_adapter_unavailable():
    with patch.dict("os.environ", {}, clear=True):
        adapter = PerplexityAdapter()
        assert not adapter.is_available()


def test_perplexity_adapter_stub():
    with patch.dict("os.environ", {"PERPLEXITY_API_KEY": "test-key"}):
        adapter = PerplexityAdapter()
        result = adapter.search("test")
        assert len(result.claims) > 0


def test_youtube_adapter_default_available():
    """YOUTUBE_TRANSCRIPT_MODE 기본값은 manual → available"""
    with patch.dict("os.environ", {}, clear=True):
        adapter = YouTubeTranscriptAdapter()
        assert adapter.is_available()


def test_youtube_adapter_disabled():
    with patch.dict("os.environ", {"YOUTUBE_TRANSCRIPT_MODE": "disabled"}):
        adapter = YouTubeTranscriptAdapter()
        assert not adapter.is_available()


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
