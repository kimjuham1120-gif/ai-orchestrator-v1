"""
src/app_dev/incremental_builder.py — Step 15 Phase A5-3

build_planner와 build_executor를 묶어서 한 Todo의 전체 빌드 사이클을 실행.

흐름:
  todo_item
    ↓ build_planner (LLM #1) → StepPlanResult (단계 계획)
    ↓ build_executor (LLM #2) → BuildOutput (실제 파일들)
    ↓
  BuildResult (통합 결과)

공개 API:
  build_one_todo(todo, referenced_context, prior_results=None) -> BuildResult

설계:
  - planner 실패 → executor 호출 안 함
  - executor 실패 → 그대로 반환 (planner 결과는 보존)
  - 둘 다 성공해야 BuildResult.ok = True
  - 시간 측정 (운영자에게 진행 상황 표시용)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.app_dev.build_planner import (
    StepPlanResult,
    plan_todo_steps,
)
from src.app_dev.build_executor import (
    BuildOutput,
    execute_steps,
)


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

@dataclass
class BuildResult:
    """한 Todo의 전체 빌드 결과 (planner + executor)."""
    plan: Optional[StepPlanResult] = None
    build: Optional[BuildOutput] = None
    error: Optional[str] = None
    duration_ms: int = 0
    todo_id: str = ""

    def to_dict(self) -> dict:
        return {
            "todo_id": self.todo_id,
            "plan": self.plan.to_dict() if self.plan else None,
            "build": self.build.to_dict() if self.build else None,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }

    @property
    def ok(self) -> bool:
        """planner와 executor 모두 성공해야 OK."""
        if self.error:
            return False
        if self.plan is None or not self.plan.ok:
            return False
        if self.build is None or not self.build.ok:
            return False
        return True

    @property
    def summary(self) -> str:
        """운영자에게 보여줄 한 줄 요약 (build의 summary 우선)."""
        if self.build and self.build.summary:
            return self.build.summary
        if self.plan and self.plan.summary:
            return self.plan.summary
        return ""

    @property
    def files(self) -> List[dict]:
        """변경될 파일 목록 (executor 결과)."""
        if self.build and self.build.files:
            return [f.to_dict() for f in self.build.files]
        return []


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def build_one_todo(
    todo: dict,
    referenced_context: Optional[dict] = None,
    prior_results: Optional[List[dict]] = None,
) -> BuildResult:
    """
    한 Todo의 전체 빌드 사이클 (planner → executor).

    Args:
      todo: TodoItem.to_dict() (id, title, description, type, estimated_files)
      referenced_context: 업로드된 기획문서 묶음 (선택)
      prior_results: 이전 완료된 Todo들의 결과 리스트
                     형식: [{"title": str, "summary": str, "files": [{"path": str}]}]

    Returns:
      BuildResult — ok=True일 때만 운영자에게 결과 표시 가능.

    실패 케이스:
      - todo 검증 실패: planner 호출 안 함, error 반환
      - planner 실패: executor 호출 안 함, plan 결과 보존
      - executor 실패: plan은 보존, build는 실패 상태
    """
    start = time.time()

    # 입력 검증
    if not isinstance(todo, dict):
        return BuildResult(
            error="todo가 dict 형식이 아님",
            duration_ms=int((time.time() - start) * 1000),
        )

    todo_id = todo.get("id") or ""
    todo_title = (todo.get("title") or "").strip()
    if not todo_title:
        return BuildResult(
            todo_id=todo_id,
            error="todo에 title이 없음",
            duration_ms=int((time.time() - start) * 1000),
        )

    # ---- 1단계: planner ----
    plan_result = plan_todo_steps(
        todo=todo,
        referenced_context=referenced_context,
        prior_results=prior_results,
    )

    if not plan_result.ok:
        return BuildResult(
            todo_id=todo_id,
            plan=plan_result,
            error=f"build_planner 실패: {plan_result.error}",
            duration_ms=int((time.time() - start) * 1000),
        )

    # ---- 2단계: executor ----
    # planner의 steps를 dict 리스트로 변환 (executor는 dict 받음)
    steps_for_executor = [s.to_dict() for s in plan_result.steps]

    build_result = execute_steps(
        todo=todo,
        steps=steps_for_executor,
        referenced_context=referenced_context,
        prior_results=prior_results,
    )

    if not build_result.ok:
        return BuildResult(
            todo_id=todo_id,
            plan=plan_result,
            build=build_result,  # 실패해도 보존 (디버깅용)
            error=f"build_executor 실패: {build_result.error}",
            duration_ms=int((time.time() - start) * 1000),
        )

    # ---- 성공 ----
    return BuildResult(
        todo_id=todo_id,
        plan=plan_result,
        build=build_result,
        duration_ms=int((time.time() - start) * 1000),
    )


# ---------------------------------------------------------------------------
# prior_results 누적 헬퍼
# ---------------------------------------------------------------------------

def build_result_to_prior_entry(
    result: BuildResult,
    todo_title: str = "",
) -> dict:
    """
    BuildResult를 prior_results 항목 형식으로 변환.

    다음 Todo 빌드 시 prior_results에 누적되어 LLM이 참조.

    Returns:
      {
        "title": str,
        "summary": str,
        "files": [{"path": str}, ...]
      }
    """
    if result is None:
        return {"title": todo_title, "summary": "", "files": []}

    summary = result.summary

    files = []
    for f in result.files:
        path = f.get("path", "") if isinstance(f, dict) else ""
        if path:
            files.append({"path": path})

    return {
        "title": todo_title,
        "summary": summary,
        "files": files,
    }
