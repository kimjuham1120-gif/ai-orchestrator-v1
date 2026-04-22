"""
Phase 2 · 병렬 리서치 (Day 116~)

역할: Phase 1의 서브주제 N개를 받아 각각에 대해 3개 리서치 어댑터를
      병렬 호출하여 결과 수집.

정책 (scope.md v4 §2 Phase 2):
  - subtopic 순차 + adapter 병렬 (API 쿼터 보호)
  - partial 허용:
    * key 없음        → 어댑터 건너뜀
    * 어댑터 1개 실패 → 해당 쌍만 기록, 나머지 계속
    * subtopic 전체 실패 → 해당 subtopic 제외
    * 모든 subtopic 실패 → 전체 예외 (silent fallback 금지)

출력 구조:
  {
    "<subtopic>": {
      "<adapter_name>": {
        "status": "success" | "failed" | "skipped",
        "claims": [...] | None,
        "error": str | None,
      },
      ...
    },
    ...
  }

환경변수:
  PHASE_2_MAX_WORKERS  — adapter 병렬 수 (기본: 3)
  PHASE_2_TIMEOUT      — 어댑터별 타임아웃 (기본: 각 어댑터 기본값 사용)
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

@dataclass
class ParallelResearchResult:
    """Phase 2 전체 결과."""
    data: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    # data = {subtopic: {adapter_name: {"status": ..., "claims": ..., "error": ...}}}

    total_subtopics: int = 0
    successful_subtopics: int = 0       # 최소 1개 어댑터 성공한 subtopic 수
    failed_subtopics: list[str] = field(default_factory=list)
    total_adapter_calls: int = 0
    successful_adapter_calls: int = 0

    def to_dict(self) -> dict:
        return {
            "data": self.data,
            "total_subtopics": self.total_subtopics,
            "successful_subtopics": self.successful_subtopics,
            "failed_subtopics": self.failed_subtopics,
            "total_adapter_calls": self.total_adapter_calls,
            "successful_adapter_calls": self.successful_adapter_calls,
        }


class AllSubtopicsFailedError(RuntimeError):
    """모든 subtopic이 실패한 경우 — silent fallback 금지 구간."""


# ---------------------------------------------------------------------------
# 어댑터 로더 (기존 v3 어댑터 재사용)
# ---------------------------------------------------------------------------

def _load_adapters() -> list:
    """
    활성화된 리서치 어댑터 인스턴스 리스트 반환.
    각 어댑터의 is_available()이 True인 것만.

    우선순위 (scope.md v4 Phase 2):
      1. Gemini Deep Research
      2. GPT Deep Research
      3. Perplexity
    """
    adapters = []

    # 어댑터는 각각 실패할 수 있으므로 개별 try
    try:
        from src.research.gemini_deep_research_adapter import GeminiDeepResearchAdapter
        adapters.append(GeminiDeepResearchAdapter())
    except Exception:
        pass

    try:
        from src.research.gpt_research_adapter import GPTResearchAdapter
        adapters.append(GPTResearchAdapter())
    except Exception:
        pass

    try:
        from src.research.perplexity_adapter import PerplexityAdapter
        adapters.append(PerplexityAdapter())
    except Exception:
        pass

    return [a for a in adapters if a.is_available()]


# ---------------------------------------------------------------------------
# 단일 어댑터 호출 (병렬 실행 단위)
# ---------------------------------------------------------------------------

def _call_adapter(adapter, subtopic: str) -> Dict[str, Any]:
    """
    단일 어댑터로 subtopic 리서치 실행.

    반환 구조:
      {
        "status": "success" | "failed",
        "claims": [{"text": ..., "source": ...}, ...] | None,
        "error": str | None,
      }

    예외 전파 없음 (partial 허용 정책).
    """
    try:
        result = adapter.search(subtopic)

        # ResearchResult 객체 또는 dict일 수 있음 — 공통 파싱
        if hasattr(result, "error") and result.error:
            return {
                "status": "failed",
                "claims": None,
                "error": str(result.error),
            }

        if hasattr(result, "claims"):
            claims_list = result.claims
        elif isinstance(result, dict):
            claims_list = result.get("claims", [])
        else:
            return {
                "status": "failed",
                "claims": None,
                "error": f"알 수 없는 응답 타입: {type(result).__name__}",
            }

        # claims를 dict 형태로 정규화
        normalized = []
        for c in claims_list or []:
            if hasattr(c, "text") and hasattr(c, "source"):
                normalized.append({"text": c.text, "source": c.source})
            elif isinstance(c, dict):
                normalized.append({
                    "text": c.get("text", ""),
                    "source": c.get("source", ""),
                })

        if not normalized:
            return {
                "status": "failed",
                "claims": None,
                "error": "응답에 claims 없음",
            }

        return {
            "status": "success",
            "claims": normalized,
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "failed",
            "claims": None,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


# ---------------------------------------------------------------------------
# 단일 subtopic 처리 (adapter 병렬)
# ---------------------------------------------------------------------------

def _process_subtopic(
    subtopic: str,
    adapters: list,
    max_workers: int,
) -> Dict[str, Dict[str, Any]]:
    """
    한 subtopic에 대해 모든 adapter를 병렬 호출.
    반환: {adapter_name: {"status": ..., "claims": ..., "error": ...}}
    """
    if not adapters:
        return {}

    result: Dict[str, Dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # adapter 별 submit
        future_to_name = {
            executor.submit(_call_adapter, adapter, subtopic): adapter.name
            for adapter in adapters
        }

        for future in as_completed(future_to_name):
            adapter_name = future_to_name[future]
            try:
                result[adapter_name] = future.result()
            except Exception as exc:
                # _call_adapter가 이미 try/except로 감쌌지만 이중 안전망
                result[adapter_name] = {
                    "status": "failed",
                    "claims": None,
                    "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                }

    return result


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def run_parallel_research(
    subtopics: List[str],
    adapters: Optional[list] = None,
) -> ParallelResearchResult:
    """
    Phase 2 · 병렬 리서치 (공개 API).

    Args:
      subtopics: Phase 1이 만든 서브주제 리스트
      adapters: 어댑터 리스트 (테스트용 주입; None이면 기본 로더 사용)

    Returns:
      ParallelResearchResult

    Raises:
      AllSubtopicsFailedError: 모든 subtopic이 실패한 경우.
                               (silent fallback 금지 구간)

    실패 정책:
      - 어댑터 key 없음 → is_available()=False → 호출 전에 제외
      - 어댑터 호출 실패 → 해당 쌍만 "failed" 기록
      - subtopic 전체 실패 → failed_subtopics에 기록, 계속 진행
      - 모든 subtopic 실패 → AllSubtopicsFailedError
    """
    if not subtopics:
        return ParallelResearchResult()

    if adapters is None:
        adapters = _load_adapters()

    # 활성 어댑터 하나도 없으면 — 모든 호출이 어차피 실패할 것이므로 즉시 에러
    if not adapters:
        raise AllSubtopicsFailedError(
            "활성화된 리서치 어댑터가 하나도 없습니다 (모든 API 키 누락)"
        )

    max_workers = int(os.environ.get("PHASE_2_MAX_WORKERS", "3"))
    max_workers = max(1, min(max_workers, 10))

    result = ParallelResearchResult(total_subtopics=len(subtopics))

    for subtopic in subtopics:
        subtopic_result = _process_subtopic(subtopic, adapters, max_workers)
        result.data[subtopic] = subtopic_result
        result.total_adapter_calls += len(subtopic_result)

        # 해당 subtopic에서 하나라도 성공한 어댑터가 있는가?
        any_success = any(
            r.get("status") == "success"
            for r in subtopic_result.values()
        )

        if any_success:
            result.successful_subtopics += 1
            result.successful_adapter_calls += sum(
                1 for r in subtopic_result.values()
                if r.get("status") == "success"
            )
        else:
            result.failed_subtopics.append(subtopic)

    # 모든 subtopic이 실패 → 전체 예외 (partial 허용의 상한)
    if result.successful_subtopics == 0 and result.total_subtopics > 0:
        raise AllSubtopicsFailedError(
            f"모든 subtopic({result.total_subtopics}개)이 리서치 실패. "
            f"개별 어댑터 에러를 확인하세요."
        )

    return result
