"""
Tavily Research Adapter — Day 49~56 범위에서 제외.

이번 프로젝트 범위(GPT + Gemini + YouTube + Perplexity)와 맞지 않아
운영 경로에서 제외. google_adapter 패턴과 동일하게 disabled 처리.

  is_available() → False (항상)
  search()       → error 반환

향후 전환 방법:
  TAVILY_API_KEY 발급 후 이 파일을 real 구현으로 교체.
"""
from __future__ import annotations

from src.research.base import BaseResearchAdapter, ResearchResult


class TavilyAdapter(BaseResearchAdapter):
    name = "tavily"

    def is_available(self) -> bool:
        return False  # disabled — 운영 범위 제외

    def search(self, query: str) -> ResearchResult:
        return ResearchResult(
            adapter_name=self.name,
            error="tavily disabled — 현재 운영 범위 제외",
        )
