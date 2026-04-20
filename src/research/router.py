"""
Research Router — 활성 어댑터를 순서대로 실행하고 번들 반환.

Research 구조 (Day 65~72 확정):

  핵심 research 축 (심층리서치):
    1. GeminiDeepResearchAdapter — real (GEMINI_API_KEY)
                                   agentic deep research + googleSearch grounding
    2. GPTResearchAdapter        — real (OPENAI_API_KEY)
                                   web_search_preview 심층리서치

  support (보조 정보 수집):
    3. PerplexityAdapter         — real (PERPLEXITY_API_KEY)  웹 보강
    4. GeminiResearchAdapter     — real (GEMINI_API_KEY)      빠른 googleSearch grounding
                                   (GeminiDeepResearch와 동일 key, 역할 다름)

  fallback:
    5. YouTubeTranscriptAdapter  — stub (real 전원 비활성일 때만)
                                   영상/실전 자료 transcript 취합

  제외:
    - TavilyAdapter: 운영 범위 제외 (disabled)
    - BraveSearchAdapter: support에서 제외 (Perplexity로 대체)
    - GoogleResearchAdapter: v1 disabled 유지

실패 정책 (v2 유지):
  - key 없음 → is_available()=False → 건너뜀
  - key 있음 + 호출 실패 → 즉시 예외 전파
  - YouTube fallback → 핵심+support 전원 비활성일 때만 실행
  - silent fallback 금지

참고: GeminiDeepResearchAdapter와 GeminiResearchAdapter는
  동일한 GEMINI_API_KEY를 사용하지만 역할이 다름:
  - GeminiDeepResearchAdapter: agentic 심층리서치 (시간 소요, 고품질)
  - GeminiResearchAdapter: 빠른 grounding search (support 역할)
"""
from __future__ import annotations

from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
from src.research.gpt_research_adapter import GPTResearchAdapter
from src.research.perplexity_adapter import PerplexityAdapter
from src.research.gemini_adapter import GeminiResearchAdapter
from src.research.youtube_adapter import YouTubeTranscriptAdapter
from src.research.evidence_bundle import EvidenceBundle, build_evidence_bundle

# ---------------------------------------------------------------------------
# 어댑터 분류
# ---------------------------------------------------------------------------

# 핵심 심층리서치 축
_DEEP_RESEARCH_CLASSES = (
    GeminiDeepResearchAdapter,  # primary: agentic deep research
    GPTResearchAdapter,          # primary: web_search_preview 심층리서치
)

# support: 보조 정보 수집
_SUPPORT_ADAPTER_CLASSES = (
    PerplexityAdapter,          # 웹 보강
    GeminiResearchAdapter,      # 빠른 googleSearch grounding
)

# fallback: 영상/실전 자료 (real 전원 비활성 시만)
_FALLBACK_ADAPTER_CLASSES = (
    YouTubeTranscriptAdapter,
)

# 기존 테스트 호환용 별칭
_REAL_ADAPTER_CLASSES = _DEEP_RESEARCH_CLASSES + _SUPPORT_ADAPTER_CLASSES
_STUB_ADAPTER_CLASSES = ()


def run_research(query: str, task_type: str = "") -> EvidenceBundle:
    """
    실패 정책 v2:
      - is_available=True 어댑터 실패 → 즉시 예외 전파
      - YouTube fallback → 핵심+support 전원 비활성일 때만 실행
    """
    deep_adapters = [cls() for cls in _DEEP_RESEARCH_CLASSES]
    support_adapters = [cls() for cls in _SUPPORT_ADAPTER_CLASSES]
    fallback_adapters = [cls() for cls in _FALLBACK_ADAPTER_CLASSES]

    active_deep = [a for a in deep_adapters if a.is_available()]
    active_support = [a for a in support_adapters if a.is_available()]

    results = []

    # 핵심 + support 순서로 실행 — 실패 시 즉시 예외 전파
    for adapter in active_deep + active_support:
        result = adapter.search(query)  # 예외는 그대로 올라감
        results.append(result)

    # YouTube fallback — 핵심+support 전원 비활성일 때만
    if not active_deep and not active_support:
        for adapter in fallback_adapters:
            if adapter.is_available():
                try:
                    results.append(adapter.search(query))
                except Exception:
                    pass  # fallback stub 실패는 무시

    return build_evidence_bundle(results)
