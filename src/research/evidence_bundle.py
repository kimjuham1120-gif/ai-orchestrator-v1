"""Evidence Bundle — 리서치 결과를 중복 제거 후 번들로 묶는다."""
from __future__ import annotations

from dataclasses import dataclass, field
from src.research.base import ResearchResult


@dataclass
class EvidenceBundle:
    """claims + sources + excerpts 묶음."""
    claims: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    adapter_summary: dict = field(default_factory=dict)  # adapter_name → claim count

    def to_dict(self) -> dict:
        return {
            "claims": self.claims,
            "sources": self.sources,
            "adapter_summary": self.adapter_summary,
        }


def build_evidence_bundle(results: list[ResearchResult]) -> EvidenceBundle:
    """여러 어댑터 결과를 하나의 EvidenceBundle로 합친다."""
    seen_claims: set[str] = set()
    seen_sources: set[str] = set()
    all_claims: list[dict] = []
    adapter_summary: dict[str, int] = {}

    for result in results:
        if result.error:
            adapter_summary[result.adapter_name] = 0
            continue
        count = 0
        for claim in result.claims:
            key = claim.claim.strip().lower()
            if key in seen_claims:
                continue
            seen_claims.add(key)
            all_claims.append({
                "claim": claim.claim,
                "source": claim.source,
                "excerpt": claim.excerpt,
                "adapter": result.adapter_name,
                "meta": claim.meta,
            })
            count += 1
            if claim.source not in seen_sources:
                seen_sources.add(claim.source)
        adapter_summary[result.adapter_name] = count

    return EvidenceBundle(
        claims=all_claims,
        sources=sorted(seen_sources),
        adapter_summary=adapter_summary,
    )
