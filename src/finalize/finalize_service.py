"""Finalize Service — 최종 요약 생성 + 상태 완료."""
from __future__ import annotations

from src.store.artifact_store import update_final_summary


def finalize_run(
    db_path: str,
    run_id: str,
    goal: str,
    approval_status: str,
    changed_files: list[str],
    test_results: str,
    run_log: str,
) -> str:
    files_str = ", ".join(changed_files) if changed_files else "(없음)"
    summary = (
        f"[completed] run_id={run_id}\n"
        f"goal: {goal}\n"
        f"approval: {approval_status}\n"
        f"changed_files: {files_str}\n"
        f"test_results: {test_results}\n"
        f"run_log: {run_log}"
    )
    update_final_summary(db_path, run_id, summary)
    return summary
