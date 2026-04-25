"""
src/research_v2/phase2_bridge.py — Phase 2 호환 브리지.

목적:
  - 새 research_v2 어댑터들을 기존 Phase 3 인터페이스와 호환되도록 연결
  - 구 src/research/parallel_router.py의 시그니처를 그대로 흉내내서
    handlers.py 변경 최소화

흐름:
  Phase 1 → 서브토픽 N개 →
    각 서브토픽마다 4개 어댑터 병렬 (run_parallel_research) →
      v3 포맷 변환 (_to_v3_format) →
        Phase2Result 집계 → Phase 3 입력 형태

v3 포맷 (Phase 3가 기대):
  {
    "<subtopic>": {
      "<adapter_name>": {
        "status": "success" | "failed" | "skipped",
        "claims": [{"text": ..., "source": ...}, ...] | None,
        "error": str | None,
      },
      ...
    },
    ...
  }

claims 변환 규칙:
  - 성공 시: report 전체 → 1개 claim (text=report, source=첫 citation URL or 어댑터명)
  - 실패 시: claims=None, error 채움
  - 스킵 시: claims=None, error=None

환경변수:
  PHASE_2_MODE          — "web_search" (기본) 또는 "deep_research"
  PHASE_2_MAX_WORKERS   — 병렬 어댑터 수 (기본: 어댑터 개수)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.research_v2.base import (
    ResearchResult,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_SKIPPED,
)
from src.research_v2.parallel_runner import (
    run_parallel_research,
    build_default_adapters,
    ParallelResult,
)


# ---------------------------------------------------------------------------
# 결과 컨테이너 (구 ParallelResearchResult와 시그니처 호환)
# ---------------------------------------------------------------------------

@dataclass
class Phase2Result:
    """Phase 2 전체 결과 — 구 ParallelResearchResult 시그니처 호환."""

    data: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    total_subtopics: int = 0
    successful_subtopics: int = 0       # 최소 1개 어댑터 성공한 subtopic 수
    failed_subtopics: List[str] = field(default_factory=list)
    total_adapter_calls: int = 0
    successful_adapter_calls: int = 0
    total_cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "data": self.data,
            "total_subtopics": self.total_subtopics,
            "successful_subtopics": self.successful_subtopics,
            "failed_subtopics": self.failed_subtopics,
            "total_adapter_calls": self.total_adapter_calls,
            "successful_adapter_calls": self.successful_adapter_calls,
            "total_cost_usd": round(self.total_cost_usd, 6),
        }


class AllSubtopicsFailedError(RuntimeError):
    """모든 서브토픽이 실패한 경우 — silent fallback 금지."""


# ---------------------------------------------------------------------------
# 핵심 공개 API — handlers.py가 호출
# ---------------------------------------------------------------------------

def run_phase_2_research(
    subtopics: List[str],
    mode: Optional[str] = None,
) -> Phase2Result:
    """
    서브토픽 리스트를 받아 각각 4개 어댑터 병렬 리서치 실행.

    Args:
        subtopics: Phase 1이 생성한 서브토픽 문자열 리스트
        mode: "web_search" (기본) 또는 "deep_research". None이면 환경변수 기반.

    Returns:
        Phase2Result — Phase 3가 바로 받을 수 있는 v3 호환 포맷

    Raises:
        AllSubtopicsFailedError: 모든 subtopic이 실패한 경우 (시도된 것 기준)
        ValueError: subtopics가 빈 리스트인 경우
    """
    if not subtopics:
        raise ValueError("subtopics가 빈 리스트입니다 — Phase 1 결과 확인 필요")

    resolved_mode = mode or os.environ.get("PHASE_2_MODE", "web_search").strip()
    if resolved_mode not in ("web_search", "deep_research"):
        resolved_mode = "web_search"  # 안전 fallback

    result = Phase2Result(total_subtopics=len(subtopics))

    for subtopic in subtopics:
        # 매 subtopic마다 새 어댑터 생성 (상태 격리)
        adapters = build_default_adapters(mode=resolved_mode)

        parallel = run_parallel_research(adapters, subtopic)

        # v3 포맷으로 변환
        result.data[subtopic] = _to_v3_format(parallel)

        # 집계
        if parallel.has_success:
            result.successful_subtopics += 1
        else:
            # 시도된 어댑터가 있는데 전부 실패/스킵일 때만 failed로 기록
            # (전부 skipped이면 "시도 자체 없음"이라 failed로 안 침)
            attempted = [r for r in parallel.results if r.status != STATUS_SKIPPED]
            if attempted:
                result.failed_subtopics.append(subtopic)

        result.total_adapter_calls += len(parallel.results)
        result.successful_adapter_calls += parallel.success_count
        result.total_cost_usd += parallel.total_cost_usd

    # 모든 subtopic 실패 시 (silent fallback 금지)
    if result.successful_subtopics == 0 and result.total_subtopics > 0:
        # 단, 모든 어댑터가 skipped였다면 (API 키 0개) AllFailedError 안 던짐
        # — 이 경우는 handlers.py가 메시지로 처리
        if result.total_adapter_calls > 0 and result.successful_adapter_calls == 0:
            attempted_subtopics = [
                s for s in subtopics
                if any(
                    a.get("status") == STATUS_FAILED
                    for a in result.data.get(s, {}).values()
                )
            ]
            if attempted_subtopics:
                raise AllSubtopicsFailedError(
                    f"모든 subtopic({result.total_subtopics}개)이 리서치 실패"
                )

    return result


# ---------------------------------------------------------------------------
# 내부 변환 — v2 ParallelResult → v3 dict 포맷
# ---------------------------------------------------------------------------

def _to_v3_format(parallel: ParallelResult) -> Dict[str, Dict[str, Any]]:
    """
    한 subtopic의 ParallelResult를 v3 포맷으로 변환.

    출력:
      {adapter_name: {"status": ..., "claims": ..., "error": ...}}
    """
    out: Dict[str, Dict[str, Any]] = {}
    for r in parallel.results:
        out[r.adapter_name] = _convert_single(r)
    return out


def _convert_single(r: ResearchResult) -> Dict[str, Any]:
    """단일 ResearchResult → v3 어댑터 결과 dict."""
    if r.status == STATUS_SUCCESS:
        # report 전체를 1개 claim으로 wrapping
        report = (r.report or "").strip()
        if not report:
            # report 비었으면 사실상 실패 처리
            return {
                "status": STATUS_FAILED,
                "claims": None,
                "error": "empty report despite success status",
            }

        # source: 첫 citation URL 우선, 없으면 어댑터명
        source = ""
        if r.citations:
            first_url = (r.citations[0].url or "").strip()
            if first_url:
                source = first_url
        if not source:
            source = r.adapter_name

        return {
            "status": STATUS_SUCCESS,
            "claims": [{"text": report, "source": source}],
            "error": None,
        }

    if r.status == STATUS_FAILED:
        return {
            "status": STATUS_FAILED,
            "claims": None,
            "error": r.error or "unknown error",
        }

    # skipped
    return {
        "status": STATUS_SKIPPED,
        "claims": None,
        "error": None,
    }
