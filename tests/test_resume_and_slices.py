"""Resume from doc_frozen + slice 반복 테스트."""
from src.orchestrator import (
    run_orchestration,
    resume_from_doc,
    run_next_slice,
    advance_current_slice,
    create_packet_if_approved,
    save_execution_result_step,
    run_verification,
    finalize_run_step,
)
from src.approval.approval_service import apply_user_approval
from src.store.artifact_store import load_artifact, update_artifact
import pytest


# ---------------------------------------------------------------------------
# resume from doc_frozen
# ---------------------------------------------------------------------------

def test_resume_from_doc_frozen(tmp_path):
    """doc_only=True → resume → approval_prepare까지 도달"""
    db = str(tmp_path / "test.db")

    # 1. doc_only로 실행 → doc_frozen
    result = run_orchestration("버그 수정해줘", db, doc_only=True)
    assert result["run_status"] == "doc_frozen"
    run_id = result["run_id"]

    # 2. resume
    updated = resume_from_doc(db, run_id)
    assert updated is not None
    assert updated["run_status"] == "waiting_approval"
    assert updated["approval_status"] == "pending"
    assert updated.get("plan") is not None
    assert updated.get("builder_output") is not None
    assert updated.get("deliverable_spec") is not None


def test_resume_from_doc_then_full_flow(tmp_path):
    """doc_frozen → resume → approve → packet → result → verify → finalize"""
    db = str(tmp_path / "test.db")
    base_dir = str(tmp_path)

    result = run_orchestration("에러 수정해줘", db, doc_only=True)
    run_id = result["run_id"]

    updated = resume_from_doc(db, run_id)
    apply_user_approval(db, run_id, "approve")

    packet = create_packet_if_approved(db, base_dir, run_id, "에러 수정", "approved")
    assert packet["packet_created"]

    save_execution_result_step(db, run_id, ["src/auth.py"], "1 passed", "fixed")
    v = run_verification(db, run_id)
    assert v["all_passed"]

    summary = finalize_run_step(db, run_id, "에러 수정", "approved", ["src/auth.py"], "1 passed", "fixed")
    assert "completed" in summary

    loaded = load_artifact(db, run_id=run_id)
    assert loaded["run_status"] == "completed"


def test_resume_rejects_non_doc_frozen(tmp_path):
    """doc_frozen이 아닌 상태에서 resume 시도 → ValueError"""
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)  # waiting_approval
    with pytest.raises(ValueError, match="doc_frozen"):
        resume_from_doc(db, result["run_id"])


# ---------------------------------------------------------------------------
# slice 반복
# ---------------------------------------------------------------------------

def test_advance_slice(tmp_path):
    """slice advance 후 current_slice_index 증가"""
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    run_id = result["run_id"]

    # slice_plan이 있어야 함
    loaded = load_artifact(db, run_id=run_id)
    assert loaded.get("slice_plan") is not None

    adv = advance_current_slice(db, run_id)
    assert adv["current_slice_index"] == 1


def test_run_next_slice_no_remaining(tmp_path):
    """남은 slice 없으면 에러 반환"""
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    run_id = result["run_id"]

    # 모든 slice advance
    loaded = load_artifact(db, run_id=run_id)
    n_slices = len(loaded.get("slice_plan", {}).get("slices", []))
    for _ in range(n_slices):
        advance_current_slice(db, run_id)

    r = run_next_slice(db, run_id)
    assert r.get("error") == "no_remaining_slices"


def test_run_next_slice_executes(tmp_path):
    """slice가 남아있으면 planner→builder→review 실행"""
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    run_id = result["run_id"]

    # current_slice_index=0 상태에서 next slice 실행
    loaded = run_next_slice(db, run_id)
    assert loaded.get("plan") is not None
    assert loaded.get("builder_output") is not None
    assert loaded.get("approval_status") == "pending"
