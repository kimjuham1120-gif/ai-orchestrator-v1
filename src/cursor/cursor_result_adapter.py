"""
Cursor Result Adapter — CursorExecutionResult → execution_result 형태 변환.

Day 65~72: 자동 실행 결과를 기존 verification/finalize 흐름과 연결.

변환 목표:
  CursorExecutionResult → {
      "changed_files": [...],
      "test_results":  "...",
      "run_log":       "...",
  }

이 형식은 save_execution_result_step() / run_verification() 과 직접 호환됨.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.cursor.cursor_executor import CursorExecutionResult


def adapt_cursor_result(result: "CursorExecutionResult") -> dict:
    """
    CursorExecutionResult → execution_result dict.

    반환 형식:
      {
          "changed_files": list[str],
          "test_results":  str,
          "run_log":       str,
      }
    """
    changed_files = result.changed_files or []
    test_results = _normalize_test_results(result.test_output)
    run_log = _build_run_log(result)

    return {
        "changed_files": changed_files,
        "test_results": test_results,
        "run_log": run_log,
    }


def _normalize_test_results(test_output: str) -> str:
    """테스트 출력을 정규화. 'N passed' 형식으로 요약."""
    if not test_output:
        return ""
    # pytest 출력에서 요약 줄 추출
    for line in reversed(test_output.splitlines()):
        line = line.strip()
        if "passed" in line or "failed" in line or "error" in line:
            return line
    return test_output[:200].strip()


def _build_run_log(result: "CursorExecutionResult") -> str:
    """실행 로그 요약 생성."""
    parts = []
    if result.job_id:
        parts.append(f"job_id={result.job_id}")
    if result.changed_files:
        parts.append(f"changed={len(result.changed_files)}개 파일")
    if result.output:
        # output 첫 줄 요약
        first_line = result.output.splitlines()[0].strip()[:100] if result.output else ""
        if first_line:
            parts.append(first_line)
    return " | ".join(parts) if parts else "Cursor auto execution completed"
