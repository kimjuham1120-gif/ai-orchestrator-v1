"""
Google Research Adapter — v1 비활성(disabled) 분류.

배경:
  Google Custom Search JSON API는 현재 신규 고객에게 닫혀 있습니다.
  v1에서는 이 어댑터를 disabled로 분류하며, 오케스트레이터 흐름을 깨지 않도록
  항상 is_available()=False / search()=error 를 반환합니다.

v2 전환 조건 (아직 미달):
  - Google Custom Search API 신규 가입 재개 확인
  - 또는 Programmable Search Engine 대체 경로 확보
  - 전환 시 brave_adapter.py 또는 tavily_adapter.py를 참고해 구현하세요.

환경변수 (예약, 현재 미사용):
  GOOGLE_RESEARCH_API_KEY
  GOOGLE_RESEARCH_CX
"""
from __future__ import annotations

from src.research.base import BaseResearchAdapter, ResearchResult

_DISABLED_REASON = (
    "Google Custom Search API — v1 disabled: "
    "신규 고객 가입이 닫혀있어 real 연결 불가. "
    "v2 전환 시 brave_adapter 또는 tavily_adapter를 사용하세요."
)


class GoogleResearchAdapter(BaseResearchAdapter):
    name = "google"

    def is_available(self) -> bool:
        return False

    def search(self, query: str) -> ResearchResult:
        return ResearchResult(
            adapter_name=self.name,
            error=_DISABLED_REASON,
        )
