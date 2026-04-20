"""Research 공통 스키마 & 베이스 클래스."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ResearchClaim:
    text: str
    source: str

    def to_dict(self) -> dict:
        return {"text": self.text, "source": self.source}


@dataclass
class ResearchResult:
    adapter_name: str
    claims: list[ResearchClaim] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "adapter": self.adapter_name,
            "claims": [c.to_dict() for c in self.claims],
            "error": self.error,
        }


class BaseResearchAdapter:
    name: str = "base"

    def is_available(self) -> bool:
        raise NotImplementedError

    def search(self, query: str) -> ResearchResult:
        raise NotImplementedError
