"""YouTube Transcript 어댑터 — v1 stub."""
from __future__ import annotations

import os
from src.research.base import ResearchAdapter, ResearchResult, ResearchClaim


class YouTubeTranscriptAdapter(ResearchAdapter):

    @property
    def name(self) -> str:
        return "youtube_transcript"

    def is_available(self) -> bool:
        mode = os.environ.get("YOUTUBE_TRANSCRIPT_MODE", "manual")
        return mode != "disabled"

    def search(self, query: str, **kwargs) -> ResearchResult:
        if not self.is_available():
            return ResearchResult(
                adapter_name=self.name,
                error="YOUTUBE_TRANSCRIPT_MODE is disabled",
            )
        # TODO: 실제 YouTube transcript 수집 구현
        return ResearchResult(
            adapter_name=self.name,
            claims=[
                ResearchClaim(
                    claim=f"[stub] YouTube transcript for: {query}",
                    source="youtube_stub",
                    excerpt="stub transcript excerpt",
                )
            ],
        )
