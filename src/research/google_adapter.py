"""Google Research Stack 어댑터 — v1 stub."""
from __future__ import annotations

import os
from src.research.base import ResearchAdapter, ResearchResult, ResearchClaim


class GoogleResearchAdapter(ResearchAdapter):

    @property
    def name(self) -> str:
        return "google_research"

    def is_available(self) -> bool:
        return bool(os.environ.get("GOOGLE_RESEARCH_API_KEY"))

    def search(self, query: str, **kwargs) -> ResearchResult:
        if not self.is_available():
            return ResearchResult(
                adapter_name=self.name,
                error="GOOGLE_RESEARCH_API_KEY not set",
            )
        # TODO: NotebookLM + Gemini Deep Research 실제 구현
        return ResearchResult(
            adapter_name=self.name,
            claims=[
                ResearchClaim(
                    claim=f"[stub] Google research result for: {query}",
                    source="google_stub",
                    excerpt="stub excerpt",
                )
            ],
        )
