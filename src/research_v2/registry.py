"""
src/research_v2/registry.py — Research 어댑터 레지스트리.

목적:
  - 이름 문자열 → 어댑터 인스턴스 매핑 ("perplexity" → PerplexityResearchAdapter)
  - mode 검증 (어댑터별 지원 모드 사전 체크)
  - 별칭 지원 ("pplx" = "perplexity")
  - 5번째 어댑터 추가 시 한 곳만 수정

공개 API:
  get_adapter(name, mode="web_search")     # 어댑터 인스턴스 생성
  list_adapter_names()                      # 등록된 어댑터 이름들 (정식 이름만)
  get_supported_modes(name)                 # 해당 어댑터의 지원 모드 리스트
  build_default_adapters(mode)              # 4개 어댑터 한 번에 생성 (parallel_runner와 동일 동작)
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from src.research_v2.base import ResearchAdapter


# ---------------------------------------------------------------------------
# 등록 정보 — 5번째 어댑터 추가 시 여기에 한 줄 추가
# ---------------------------------------------------------------------------

# 모드 상수
MODE_WEB_SEARCH = "web_search"
MODE_DEEP_RESEARCH = "deep_research"


def _make_perplexity(mode: str) -> ResearchAdapter:
    from src.research_v2.perplexity_adapter import PerplexityResearchAdapter
    return PerplexityResearchAdapter(mode=mode)


def _make_openai(mode: str) -> ResearchAdapter:
    from src.research_v2.openai_adapter import OpenAIResearchAdapter
    return OpenAIResearchAdapter(mode=mode)


def _make_gemini(mode: str) -> ResearchAdapter:
    from src.research_v2.gemini_adapter import GeminiResearchAdapter
    return GeminiResearchAdapter(mode=mode)


def _make_claude(mode: str) -> ResearchAdapter:
    """Claude는 web_search만 지원. mode 인자 무시."""
    from src.research_v2.claude_adapter import ClaudeResearchAdapter
    return ClaudeResearchAdapter()


# 등록 테이블
# (canonical_name → {factory, supported_modes, aliases})
_REGISTRY: Dict[str, Dict] = {
    "perplexity": {
        "factory": _make_perplexity,
        "supported_modes": [MODE_WEB_SEARCH, MODE_DEEP_RESEARCH],
        "aliases": ["pplx", "sonar"],
    },
    "openai": {
        "factory": _make_openai,
        "supported_modes": [MODE_WEB_SEARCH, MODE_DEEP_RESEARCH],
        "aliases": ["gpt", "o4"],
    },
    "gemini": {
        "factory": _make_gemini,
        "supported_modes": [MODE_WEB_SEARCH, MODE_DEEP_RESEARCH],
        "aliases": ["google"],
    },
    "claude": {
        "factory": _make_claude,
        "supported_modes": [MODE_WEB_SEARCH],  # DR API 없음
        "aliases": ["anthropic"],
    },
}


# ---------------------------------------------------------------------------
# 이름 정규화
# ---------------------------------------------------------------------------

def _resolve_canonical_name(name: str) -> Optional[str]:
    """
    별칭/대소문자 정규화 → canonical name.

    예:
      "perplexity" → "perplexity"
      "PPLX"       → "perplexity"
      "  Sonar  "  → "perplexity"
      "unknown"    → None
    """
    if not isinstance(name, str):
        return None
    norm = name.strip().lower()
    if not norm:
        return None

    if norm in _REGISTRY:
        return norm

    for canonical, info in _REGISTRY.items():
        if norm in info["aliases"]:
            return canonical

    return None


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def list_adapter_names() -> List[str]:
    """등록된 어댑터의 정식 이름 리스트 (별칭 제외)."""
    return list(_REGISTRY.keys())


def get_supported_modes(name: str) -> List[str]:
    """
    어댑터가 지원하는 모드 리스트.

    Raises:
        ValueError: 등록되지 않은 어댑터 이름
    """
    canonical = _resolve_canonical_name(name)
    if canonical is None:
        raise ValueError(
            f"unknown adapter '{name}'. available: {list_adapter_names()}"
        )
    return list(_REGISTRY[canonical]["supported_modes"])


def get_adapter(
    name: str, mode: str = MODE_WEB_SEARCH
) -> ResearchAdapter:
    """
    이름으로 어댑터 인스턴스 생성.

    Args:
        name: 어댑터 이름 (정식 이름 또는 별칭, 대소문자 무관)
        mode: "web_search" (기본) 또는 "deep_research"
              어댑터가 지원하지 않는 모드면 ValueError

    Returns:
        ResearchAdapter 인스턴스

    Raises:
        ValueError: 알 수 없는 이름 또는 미지원 모드

    Note:
        Claude처럼 단일 모드만 지원하는 어댑터는 mode 인자를 무시함.
        하지만 deep_research를 명시적으로 요청하면 ValueError로 거부 (실수 방지).
    """
    canonical = _resolve_canonical_name(name)
    if canonical is None:
        raise ValueError(
            f"unknown adapter '{name}'. available: {list_adapter_names()}"
        )

    info = _REGISTRY[canonical]
    supported = info["supported_modes"]

    if mode not in supported:
        raise ValueError(
            f"adapter '{canonical}' does not support mode '{mode}'. "
            f"supported: {supported}"
        )

    factory: Callable[[str], ResearchAdapter] = info["factory"]
    return factory(mode)


def build_default_adapters(
    mode: str = MODE_WEB_SEARCH,
) -> List[ResearchAdapter]:
    """
    4개 기본 어댑터 세트 생성.

    Args:
        mode: 모든 어댑터에 적용할 모드.
              Claude는 mode 무관하게 항상 web_search.

    Returns:
        [Perplexity, OpenAI, Gemini, Claude]

    Note:
        mode="deep_research"여도 Claude는 web_search로 자동 fallback.
        (다른 어댑터는 모두 deep_research 모드)
    """
    adapters: List[ResearchAdapter] = []

    for canonical_name in list_adapter_names():
        info = _REGISTRY[canonical_name]
        # 어댑터가 요청 모드 지원하면 그 모드로, 아니면 web_search로
        adapter_mode = (
            mode if mode in info["supported_modes"] else MODE_WEB_SEARCH
        )
        factory = info["factory"]
        adapters.append(factory(adapter_mode))

    return adapters
