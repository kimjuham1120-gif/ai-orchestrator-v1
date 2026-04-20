"""
Brave Search Adapter — v1 real research 어댑터.

Google Custom Search API 신규 가입 불가로 인한 대체 어댑터.

환경변수:
  BRAVE_SEARCH_API_KEY — https://brave.com/search/api/ 에서 발급 (Free: 2,000 req/월)

동작 규칙 (조용한 fake 폴백 금지):
  key 없음          → ResearchResult(error=...) 반환, is_available()=False
  key 있음 + 성공   → real claims 반환
  key 있음 + 실패   → 예외 전파 (HTTPStatusError / TimeoutException 등)

응답 구조:
  web.results[].description → ResearchClaim.text
  web.results[].url         → ResearchClaim.source
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

from src.research.base import BaseResearchAdapter, ResearchClaim, ResearchResult

_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_DEFAULT_COUNT = 5
_TIMEOUT = 10.0


class BraveSearchAdapter(BaseResearchAdapter):
    name = "brave"

    def __init__(self) -> None:
        self._api_key: Optional[str] = os.environ.get("BRAVE_SEARCH_API_KEY")

    def is_available(self) -> bool:
        return bool(self._api_key)

    def search(self, query: str) -> ResearchResult:
        if not self.is_available():
            return ResearchResult(
                adapter_name=self.name,
                error="BRAVE_SEARCH_API_KEY not set",
            )

        # key 있음 → real 호출. 실패 시 예외 전파 (조용한 폴백 없음)
        resp = httpx.get(
            _BRAVE_SEARCH_URL,
            params={"q": query, "count": _DEFAULT_COUNT},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": self._api_key,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()  # HTTP 오류 → HTTPStatusError 전파

        data = resp.json()
        web_results = data.get("web", {}).get("results", [])
        claims = [
            ResearchClaim(
                text=item.get("description", item.get("title", "")),
                source=item.get("url", ""),
            )
            for item in web_results
            if item.get("description") or item.get("title")
        ]
        return ResearchResult(adapter_name=self.name, claims=claims)
