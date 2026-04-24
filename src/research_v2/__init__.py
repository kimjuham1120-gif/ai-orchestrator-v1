"""
src/research_v2 — Phase 2 Deep Research 어댑터 패키지.

Day 137~ : 4-AI Deep Research 재구성.

공개 API:
  from src.research_v2 import (
      ResearchAdapter, ResearchResult, ResearchCitation,
      STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED,
  )
"""
from src.research_v2.base import (
    ResearchAdapter,
    ResearchResult,
    ResearchCitation,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_SKIPPED,
)

__all__ = [
    "ResearchAdapter",
    "ResearchResult",
    "ResearchCitation",
    "STATUS_SUCCESS",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
]
