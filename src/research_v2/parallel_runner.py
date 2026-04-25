"""
src/research_v2/parallel_runner.py — 다중 어댑터 병렬 실행 러너.

Phase 2의 핵심 오케스트레이터:
  - 등록된 ResearchAdapter들을 ThreadPoolExecutor로 동시 실행
  - 각 어댑터는 독립된 스레드 → 한 쪽이 느려도 전체는 빠른 쪽 속도
  - 일부 실패해도 나머지 결과는 수집 (best-effort aggregation)
  - 전체 결과를 ParallelResult로 집계

기본 동작:
  - max_workers = None (len(adapters) 개수만큼)
  - 개별 타임아웃 = 각 어댑터의 default_timeout (모드별로 다름)
  - 전체 타임아웃 = 개별 중 최대값 + 30초 버퍼

실패 정책:
  - skipped (키 없음)  → failed 아님, 정상 스킵
  - failed (HTTP/파싱) → 기록만, 다른 어댑터는 계속
  - 예외 (버그)         → ResearchResult(status=FAILED)로 포착
  - 모두 실패해도 예외 안 던짐 — 호출자가 ParallelResult.has_success로 판단
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional

from src.research_v2.base import (
    ResearchAdapter,
    ResearchResult,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_SKIPPED,
)


# ---------------------------------------------------------------------------
# 결과 컨테이너
# ---------------------------------------------------------------------------

@dataclass
class ParallelResult:
    """다중 어댑터 병렬 실행 결과."""

    query: str
    results: List[ResearchResult] = field(default_factory=list)
    total_duration_ms: int = 0

    # ---------- 파생 속성 ----------

    @property
    def successful(self) -> List[ResearchResult]:
        return [r for r in self.results if r.status == STATUS_SUCCESS]

    @property
    def failed(self) -> List[ResearchResult]:
        return [r for r in self.results if r.status == STATUS_FAILED]

    @property
    def skipped(self) -> List[ResearchResult]:
        return [r for r in self.results if r.status == STATUS_SKIPPED]

    @property
    def success_count(self) -> int:
        return len(self.successful)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def has_success(self) -> bool:
        """하나라도 성공했나?"""
        return self.success_count > 0

    @property
    def all_failed(self) -> bool:
        """시도한 것 중 전부 실패? (스킵은 제외)"""
        attempted = [r for r in self.results if r.status != STATUS_SKIPPED]
        if not attempted:
            return False  # 다 스킵된 건 fail 아님
        return all(r.status == STATUS_FAILED for r in attempted)

    @property
    def total_cost_usd(self) -> float:
        return round(sum(r.cost_usd or 0.0 for r in self.results), 6)

    # ---------- 직렬화 ----------

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "total_duration_ms": self.total_duration_ms,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "total_cost_usd": self.total_cost_usd,
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def run_parallel_research(
    adapters: List[ResearchAdapter],
    query: str,
    timeout: Optional[float] = None,
    max_workers: Optional[int] = None,
) -> ParallelResult:
    """
    여러 어댑터를 동시 실행해 결과 집계.

    Args:
        adapters: 실행할 어댑터 리스트 (빈 리스트 허용)
        query: 모든 어댑터에 전달할 질문
        timeout: 전체 타임아웃 (초). None이면 개별 어댑터 타임아웃의 최대값 + 30s.
                 개별 어댑터 타임아웃은 각 어댑터가 research() 내부에서 관리.
        max_workers: 동시 실행 수. None이면 len(adapters).

    Returns:
        ParallelResult — 모든 결과 집계 (성공/실패/스킵 포함)

    빈 어댑터 리스트는 빈 ParallelResult 반환 (예외 아님).
    """
    start = time.time()

    # 빈 리스트 방어
    if not adapters:
        return ParallelResult(query=query, results=[], total_duration_ms=0)

    # max_workers 기본값
    workers = max_workers if max_workers and max_workers > 0 else len(adapters)

    # 전체 타임아웃 기본값
    overall_timeout = _resolve_overall_timeout(adapters, timeout)

    results: List[ResearchResult] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_adapter: dict = {}
        for adapter in adapters:
            future = executor.submit(_safe_research, adapter, query)
            future_to_adapter[future] = adapter

        # as_completed — 끝난 순서대로 수확
        try:
            for future in as_completed(future_to_adapter.keys(), timeout=overall_timeout):
                adapter = future_to_adapter[future]
                try:
                    result = future.result(timeout=0)  # 이미 완료됨
                except Exception as e:
                    # _safe_research가 모든 예외 잡지만, 혹시 몰라 방어
                    result = ResearchResult(
                        adapter_name=getattr(adapter, "name", "unknown"),
                        status=STATUS_FAILED,
                        error=f"executor error: {e}",
                    )
                results.append(result)
        except TimeoutError:
            # 전체 타임아웃 초과 — 미완료 future들은 FAILED로 기록
            completed_futures = {f for f in future_to_adapter if f.done()}
            for future, adapter in future_to_adapter.items():
                if future in completed_futures:
                    continue
                # 아직 안 끝났으면 취소 시도 후 timeout 결과
                future.cancel()
                results.append(ResearchResult(
                    adapter_name=getattr(adapter, "name", "unknown"),
                    status=STATUS_FAILED,
                    error=f"overall timeout after {overall_timeout}s",
                ))

    total_ms = int((time.time() - start) * 1000)
    return ParallelResult(
        query=query,
        results=results,
        total_duration_ms=total_ms,
    )


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _safe_research(adapter: ResearchAdapter, query: str) -> ResearchResult:
    """
    어댑터 실행을 예외로부터 보호.
    ResearchAdapter.research()는 이미 내부에서 예외를 잡지만,
    __init__/프로퍼티 버그 등 초기화 단계 예외도 대비.
    """
    try:
        return adapter.research(query)
    except Exception as e:
        return ResearchResult(
            adapter_name=getattr(adapter, "name", "unknown"),
            status=STATUS_FAILED,
            error=f"unhandled exception: {e}",
        )


def _resolve_overall_timeout(
    adapters: List[ResearchAdapter], timeout: Optional[float]
) -> float:
    """
    전체 타임아웃 결정.
    사용자 지정 > 개별 어댑터 default_timeout 최대값 + 30s 버퍼
    """
    if timeout is not None and timeout > 0:
        return float(timeout)

    max_individual = 0.0
    for adapter in adapters:
        try:
            t = float(adapter.default_timeout)
            if t > max_individual:
                max_individual = t
        except Exception:
            continue

    if max_individual <= 0:
        return 300.0  # fallback 5분
    return max_individual + 30.0


# ---------------------------------------------------------------------------
# build_default_adapters — registry로 위임 (하위호환 유지)
# ---------------------------------------------------------------------------

def build_default_adapters(mode: str = "web_search") -> List[ResearchAdapter]:
    """
    4개 어댑터 기본 세트 생성 — registry로 위임.

    이 함수는 phase2_bridge.py 등 기존 호출자가 그대로 쓰도록 유지.
    실제 구현은 src.research_v2.registry로 이동했음.

    Args:
        mode: "web_search" (기본) 또는 "deep_research"
              Claude는 mode 무관하게 항상 web_search

    Returns:
        [Perplexity, OpenAI, Gemini, Claude]
    """
    from src.research_v2.registry import build_default_adapters as _build
    return _build(mode=mode)
