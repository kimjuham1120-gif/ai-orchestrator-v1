"""리서치 어댑터 공통 인터페이스."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResearchClaim:
    """단일 근거 항목."""
    claim:   str              # 핵심 주장
    source:  str              # 출처 식별자
    excerpt: str = ""         # 발췌
    meta:    dict = field(default_factory=dict)


@dataclass
class ResearchResult:
    """어댑터 반환 결과."""
    adapter_name: str
    claims:       list[ResearchClaim] = field(default_factory=list)
    raw_data:     Any = None
    error:        str | None = None

    def to_dict(self) -> dict:
        return {
            "adapter_name": self.adapter_name,
            "claims": [
                {"claim": c.claim, "source": c.source, "excerpt": c.excerpt, "meta": c.meta}
                for c in self.claims
            ],
            "error": self.error,
        }


class ResearchAdapter(ABC):
    """모든 리서치 어댑터가 구현해야 하는 인터페이스."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def is_available(self) -> bool:
        """API 키 등 사전 조건 충족 여부."""
        ...

    @abstractmethod
    def search(self, query: str, **kwargs) -> ResearchResult:
        """검색 실행. 실패 시 error 필드를 채운 ResearchResult 반환."""
        ...
