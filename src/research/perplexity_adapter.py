"""Perplexity Search API 어댑터 — v1 stub."""
from __future__ import annotations

import os
from src.research.base import ResearchAdapter, ResearchResult, ResearchClaim


class PerplexityAdapter(ResearchAdapter):

    @property
    def name(self) -> str:
        return "perplexity"

    def is_available(self) -> bool:
        return bool(os.environ.get("PERPLEXITY_API_KEY"))

    def search(self, query: str, **kwargs) -> ResearchResult:
        if not self.is_available():
            return ResearchResult(
                adapter_name=self.name,
                error="PERPLEXITY_API_KEY not set",
            )
        # TODO: Perplexity Search API 실제 구현
        return ResearchResult(
            adapter_name=self.name,
            claims=[
                ResearchClaim(
                    claim=f"[stub] Perplexity result for: {query}",
                    source="perplexity_stub",
                    excerpt="stub excerpt",
                )
            ],
        )
