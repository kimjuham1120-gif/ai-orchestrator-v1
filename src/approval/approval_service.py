"""Approval 서비스 — v1 artifact_store 기반."""
from __future__ import annotations

from src.store.artifact_store import update_approval


def apply_user_approval(
    db_path: str,
    run_id: str,
    user_decision: str,
) -> None:
    """사용자 승인/거절 반영."""
    if user_decision == "approve":
        update_approval(db_path, run_id, status="approved", reason="user_approved")
        return
    if user_decision == "reject":
        update_approval(db_path, run_id, status="rejected", reason="user_rejected")
        return
    raise ValueError("user_decision must be 'approve' or 'reject'")
