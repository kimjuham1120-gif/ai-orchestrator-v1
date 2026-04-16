"""Finalize 서비스 — 최종 요약 생성 + artifact 저장."""
from __future__ import annotations

from src.finalize.finalizer import build_final_summary
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
    """최종 요약을 생성하고 artifact store에 저장한다."""
    summary = build_final_summary(
        goal=goal,
        approval_status=approval_status,
        changed_files=changed_files,
        test_results=test_results,
        run_log=run_log,
        final_status="completed",
    )
    update_final_summary(db_path, run_id, summary)
    return summary
