"""Research Router — 분류 결과에 따라 어댑터를 선택하고 번들을 생성한다."""
from __future__ import annotations

from src.research.base import ResearchAdapter, ResearchResult
from src.research.google_adapter import GoogleResearchAdapter
from src.research.perplexity_adapter import PerplexityAdapter
from src.research.youtube_adapter import YouTubeTranscriptAdapter
from src.research.evidence_bundle import EvidenceBundle, build_evidence_bundle


# 전역 어댑터 레지스트리
_ADAPTERS: list[ResearchAdapter] = [
    GoogleResearchAdapter(),
    PerplexityAdapter(),
    YouTubeTranscriptAdapter(),
]


def run_research(query: str, task_type: str = "") -> EvidenceBundle:
    """
    사용 가능한 모든 어댑터로 검색 후 EvidenceBundle 반환.
    어댑터가 모두 unavailable이면 빈 번들 반환.
    """
    results: list[ResearchResult] = []
    for adapter in _ADAPTERS:
        result = adapter.search(query)
        results.append(result)
    return build_evidence_bundle(results)
