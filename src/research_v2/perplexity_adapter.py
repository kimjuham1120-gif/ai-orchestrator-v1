"""
src/research_v2/perplexity_adapter.py — Perplexity 어댑터 (듀얼 모드).

벤더: Perplexity AI
API: https://api.perplexity.ai/chat/completions (OpenAI 호환)

모드:
  - "web_search"   (기본): sonar-pro, 60초 타임아웃, 빠른 일반 웹검색
  - "deep_research":       sonar-deep-research, 600초, 자율 다단계 리서치

환경변수:
  PERPLEXITY_API_KEY — 필수

가격:
  sonar-pro:             $3/1M input, $15/1M output
  sonar-deep-research:   $2/1M input, $8/1M output + $5/1000 searches
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx

from src.research_v2.base import (
    ResearchAdapter,
    ResearchResult,
    ResearchCitation,
    STATUS_SUCCESS,
    STATUS_FAILED,
)


# ---------------------------------------------------------------------------
# 모드 상수
# ---------------------------------------------------------------------------

MODE_WEB_SEARCH = "web_search"
MODE_DEEP_RESEARCH = "deep_research"
_VALID_MODES = {MODE_WEB_SEARCH, MODE_DEEP_RESEARCH}

_API_URL = "https://api.perplexity.ai/chat/completions"

# 모드별 설정
_MODE_CONFIG = {
    MODE_WEB_SEARCH: {
        "model": "sonar-pro",
        "timeout": 60.0,
        "input_rate_per_m": 3.0,
        "output_rate_per_m": 15.0,
        "has_search_cost": False,
    },
    MODE_DEEP_RESEARCH: {
        "model": "sonar-deep-research",
        "timeout": 600.0,
        "input_rate_per_m": 2.0,
        "output_rate_per_m": 8.0,
        "has_search_cost": True,  # $5/1000 searches
    },
}

_SEARCH_RATE_PER_1000 = 5.0


class PerplexityResearchAdapter(ResearchAdapter):
    """Perplexity 어댑터 — web_search 또는 deep_research 모드."""

    name = "perplexity_research"

    def __init__(self, mode: str = MODE_WEB_SEARCH):
        if mode not in _VALID_MODES:
            raise ValueError(
                f"invalid mode '{mode}'. must be one of {sorted(_VALID_MODES)}"
            )
        self.mode = mode
        self._config = _MODE_CONFIG[mode]

    # ---------------------------------------------------------------------
    # 기본 타임아웃 — 모드별
    # ---------------------------------------------------------------------

    @property
    def default_timeout(self) -> float:
        return self._config["timeout"]

    # ---------------------------------------------------------------------
    # 가용성
    # ---------------------------------------------------------------------

    def is_available(self) -> bool:
        key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
        return bool(key)

    # ---------------------------------------------------------------------
    # 본 호출
    # ---------------------------------------------------------------------

    def _do_research(self, query: str, timeout: float) -> ResearchResult:
        api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
        model = self._config["model"]

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert research assistant. "
                        "Provide a comprehensive, well-structured markdown report "
                        "with clear sections, headings, and cited sources."
                    ),
                },
                {"role": "user", "content": query},
            ],
        }

        response = httpx.post(
            _API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )

        if response.status_code >= 400:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"HTTP {response.status_code}: {response.text[:200]}",
            )

        body = response.json()
        return self._parse_response(body, model)

    # ---------------------------------------------------------------------
    # 응답 파싱
    # ---------------------------------------------------------------------

    def _parse_response(self, body: Dict[str, Any], model: str) -> ResearchResult:
        """Perplexity 응답 → ResearchResult."""
        try:
            report = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error="malformed response: no choices[0].message.content",
                raw_meta={"body_keys": list(body.keys()) if isinstance(body, dict) else []},
            )

        citations = _parse_citations(body.get("citations"))

        usage = body.get("usage") or {}
        cost = _calculate_cost(usage, self._config)

        return ResearchResult(
            adapter_name=self.name,
            status=STATUS_SUCCESS,
            report=report,
            citations=citations,
            model=model,
            cost_usd=cost,
            raw_meta={"usage": usage, "mode": self.mode},
        )


# ---------------------------------------------------------------------------
# 헬퍼 (모듈 레벨)
# ---------------------------------------------------------------------------

def _parse_citations(raw: Any) -> List[ResearchCitation]:
    """
    Perplexity citations 파싱.
    - URL 문자열 배열 또는 dict 배열 둘 다 지원.
    """
    if not raw or not isinstance(raw, list):
        return []

    result: List[ResearchCitation] = []
    for item in raw:
        if isinstance(item, str):
            url = item.strip()
            if url:
                result.append(ResearchCitation(url=url))
        elif isinstance(item, dict):
            url = str(item.get("url") or item.get("link") or "").strip()
            if url:
                result.append(ResearchCitation(
                    url=url,
                    title=str(item.get("title", "")),
                    snippet=str(item.get("snippet", "")),
                ))
    return result


def _calculate_cost(usage: Dict[str, Any], config: Dict[str, Any]) -> float:
    """
    모드별 가격 테이블로 비용 계산.

    web_search:    input + output만
    deep_research: input + output + num_search_queries × $5/1000
    """
    if not isinstance(usage, dict):
        return 0.0

    def _safe_int(val) -> int:
        try:
            return max(0, int(val or 0))
        except (TypeError, ValueError):
            return 0

    prompt_tokens = _safe_int(usage.get("prompt_tokens"))
    completion_tokens = _safe_int(usage.get("completion_tokens"))

    cost = (
        (prompt_tokens * config["input_rate_per_m"]) / 1_000_000.0
        + (completion_tokens * config["output_rate_per_m"]) / 1_000_000.0
    )

    if config["has_search_cost"]:
        num_searches = _safe_int(usage.get("num_search_queries"))
        cost += (num_searches * _SEARCH_RATE_PER_1000) / 1000.0

    return round(cost, 6)


# ---------------------------------------------------------------------------
# 하위호환 — 기존 이름 유지
# ---------------------------------------------------------------------------

class PerplexityDeepResearchAdapter(PerplexityResearchAdapter):
    """
    하위호환 별칭 — deep_research 모드로 고정.
    기존 코드에서 이 이름으로 import하던 것 보호.
    """

    name = "perplexity_sonar_dr"

    def __init__(self):
        super().__init__(mode=MODE_DEEP_RESEARCH)
