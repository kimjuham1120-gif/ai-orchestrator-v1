"""Evidence Bundle 빌더 — 중복 제거 포함."""
from __future__ import annotations
from dataclasses import dataclass, field

from src.research.base import ResearchClaim, ResearchResult


@dataclass
class EvidenceBundle:
    claims: list[ResearchClaim] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "claims": [c.to_dict() for c in self.claims],
            "sources": self.sources,
        }


def build_evidence_bundle(results: list[ResearchResult]) -> EvidenceBundle:
    seen: set[str] = set()
    claims: list[ResearchClaim] = []
    sources: list[str] = []

    for r in results:
        if r.error:
            continue
        for c in r.claims:
            key = f"{c.text}|{c.source}"
            if key not in seen:
                seen.add(key)
                claims.append(c)
                if c.source not in sources:
                    sources.append(c.source)

    return EvidenceBundle(claims=claims, sources=sources)
