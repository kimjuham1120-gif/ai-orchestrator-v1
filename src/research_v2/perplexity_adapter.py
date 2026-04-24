"""
src/research_v2/perplexity_adapter.py — Perplexity Sonar Deep Research 어댑터.

벤더: Perplexity AI
모델: sonar-deep-research
API: https://api.perplexity.ai/chat/completions (OpenAI 호환)

특징:
  - 자율 다단계 검색 + 종합 리서치
  - citations 배열로 소스 URL 반환
  - 소요 시간: 3~8분 (기본 타임아웃 600초)
  - 가격: $2/1M input + $8/1M output + $5/1000 검색

환경변수:
  PERPLEXITY_API_KEY — 필수

응답 포맷 (Perplexity):
  {
    "choices": [{"message": {"content": "...보고서..."}}],
    "citations": ["https://a.com", "https://b.com", ...],
    "usage": {
      "prompt_tokens": 120,
      "completion_tokens": 3500,
      "total_tokens": 3620,
      "num_search_queries": 28  # Deep Research 특수 필드 (있으면)
    }
  }

주: citations 는 URL만 배열. 제목/스니펫은 별도 제공 안 함 (주의).
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
# 상수
# ---------------------------------------------------------------------------

_API_URL = "https://api.perplexity.ai/chat/completions"
_MODEL_ID = "sonar-deep-research"

# 가격 (per 1M tokens)
_INPUT_RATE_PER_M = 2.0
_OUTPUT_RATE_PER_M = 8.0

# 검색 1000건당 $5
_SEARCH_RATE_PER_1000 = 5.0


class PerplexityDeepResearchAdapter(ResearchAdapter):
    """Perplexity Sonar Deep Research 어댑터."""

    name = "perplexity_sonar_dr"
    default_timeout = 600.0  # Deep Research는 오래 걸림

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

        payload = {
            "model": _MODEL_ID,
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

        # HTTP 4xx / 5xx → 실패
        if response.status_code >= 400:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=_MODEL_ID,
                error=f"HTTP {response.status_code}: {response.text[:200]}",
            )

        body = response.json()
        return self._parse_response(body)

    # ---------------------------------------------------------------------
    # 응답 파싱
    # ---------------------------------------------------------------------

    def _parse_response(self, body: Dict[str, Any]) -> ResearchResult:
        """Perplexity 응답 → ResearchResult."""
        # 보고서 추출
        try:
            report = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=_MODEL_ID,
                error="malformed response: no choices[0].message.content",
                raw_meta={"body_keys": list(body.keys()) if isinstance(body, dict) else []},
            )

        # 인용 파싱
        citations = _parse_citations(body.get("citations"))

        # 비용 계산
        usage = body.get("usage") or {}
        cost = _calculate_cost(usage)

        return ResearchResult(
            adapter_name=self.name,
            status=STATUS_SUCCESS,
            report=report,
            citations=citations,
            model=_MODEL_ID,
            cost_usd=cost,
            raw_meta={"usage": usage},
        )


# ---------------------------------------------------------------------------
# 헬퍼 (모듈 레벨 — 테스트 용이)
# ---------------------------------------------------------------------------

def _parse_citations(raw: Any) -> List[ResearchCitation]:
    """
    Perplexity citations는 URL 문자열 배열.
    다만 일부 버전에서 dict도 반환할 수 있어 둘 다 처리.
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


def _calculate_cost(usage: Dict[str, Any]) -> float:
    """
    usage 기반 비용 계산 (USD).

    구성:
      입력 토큰 × $2/1M
      + 출력 토큰 × $8/1M
      + 검색 횟수 × $5/1000

    방어적: 음수/None/비숫자 → 0 처리.
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
    num_searches = _safe_int(usage.get("num_search_queries"))

    cost = (
        (prompt_tokens * _INPUT_RATE_PER_M) / 1_000_000.0
        + (completion_tokens * _OUTPUT_RATE_PER_M) / 1_000_000.0
        + (num_searches * _SEARCH_RATE_PER_1000) / 1000.0
    )
    return round(cost, 6)
