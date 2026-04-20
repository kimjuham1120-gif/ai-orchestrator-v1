"""
YouTube Transcript Adapter — interface 완성 + stub 구현.

환경변수:
  YOUTUBE_TRANSCRIPT_MODE — 'manual'(기본) | 'auto' | 'disabled'

'disabled' 이면 is_available() == False.
그 외에는 stub 데이터 반환 (real youtube-transcript-api 연동은 v2).
"""
from __future__ import annotations

import os

from src.research.base import BaseResearchAdapter, ResearchClaim, ResearchResult

_YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"  # 준비만


class YouTubeTranscriptAdapter(BaseResearchAdapter):
    name = "youtube"

    def __init__(self) -> None:
        self._mode = os.environ.get("YOUTUBE_TRANSCRIPT_MODE", "manual").lower()

    def is_available(self) -> bool:
        return self._mode != "disabled"

    def search(self, query: str) -> ResearchResult:
        if not self.is_available():
            return ResearchResult(
                adapter_name=self.name,
                error="YOUTUBE_TRANSCRIPT_MODE=disabled",
            )
        # stub
        return ResearchResult(
            adapter_name=self.name,
            claims=[
                ResearchClaim(
                    text=f"[YouTube stub] {query}: 영상 트랜스크립트 요약 1",
                    source="https://stub.youtube.example/1",
                ),
                ResearchClaim(
                    text=f"[YouTube stub] {query}: 영상 트랜스크립트 요약 2",
                    source="https://stub.youtube.example/2",
                ),
            ],
        )
