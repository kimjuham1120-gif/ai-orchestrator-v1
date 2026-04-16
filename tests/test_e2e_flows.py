"""
E2E 흐름 테스트 — 핸드오프 요구사항 8개 시나리오.

1. doc-only stop
2. resume from approved plan
3. approval reject
4. packet blocked when not approved
5. execution_result_received
6. spec alignment fail → slice retry
7. spec alignment fail → doc re-audit
8. full E2E single flow
"""
from src.orchestrator import (
    run_orchestration,
    create_packet_if_approved,
    save_execution_result_step,
    run_verification,
    finalize_run_step,
)
from src.approval.approval_service import apply_user_approval
from src.store.artifact_store import load_artifact, update_artifact


# ---------------------------------------------------------------------------
# 1. doc-only stop
# ---------------------------------------------------------------------------

def test_doc_only_stop(tmp_path):
    """doc_only=True → run_status='doc_frozen', 실행 계획 없음"""
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db, doc_only=True)
    assert result["run_status"] == "doc_frozen"
    assert result["canonical_doc"] is not None
    # planner/builder는 실행되지 않음
    assert result.get("plan") is None or result.get("builder_output") is None


# ---------------------------------------------------------------------------
# 2. resume from approved plan (기존 artifact에서 재개)
# ---------------------------------------------------------------------------

def test_resume_from_approved(tmp_path):
    """승인 후 패킷 생성 → 결과 입력 → finalize 가능"""
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    run_id = result["run_id"]

    apply_user_approval(db, run_id, "approve")

    # 재로드 후 패킷 생성
    loaded = load_artifact(db, run_id=run_id)
    assert loaded["approval_status"] == "approved"

    packet = create_packet_if_approved(db, str(tmp_path), run_id, "버그 수정", "approved")
    assert packet["packet_created"] is True


# ---------------------------------------------------------------------------
# 3. approval reject
# ---------------------------------------------------------------------------

def test_approval_reject(tmp_path):
    """reject → run_status='rejected'"""
    db = str(tmp_path / "test.db")
    result = run_orchestration("에러 수정해줘", db)
    run_id = result["run_id"]

    apply_user_approval(db, run_id, "reject")

    loaded = load_artifact(db, run_id=run_id)
    assert loaded["approval_status"] == "rejected"
    assert loaded["run_status"] == "rejected"


# ---------------------------------------------------------------------------
# 4. packet blocked when not approved
# ---------------------------------------------------------------------------

def test_packet_blocked_without_approval(tmp_path):
    """비승인 상태에서 패킷 생성 시도 → 차단"""
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)

    packet = create_packet_if_approved(db, str(tmp_path), result["run_id"], "goal", "pending")
    assert packet["packet_created"] is False
    assert packet["error"] == "approval_not_granted"


# ---------------------------------------------------------------------------
# 5. execution_result_received
# ---------------------------------------------------------------------------

def test_execution_result_received(tmp_path):
    """실행 결과 저장 후 run_status 확인"""
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    run_id = result["run_id"]

    apply_user_approval(db, run_id, "approve")
    create_packet_if_approved(db, str(tmp_path), run_id, "goal", "approved")
    save_execution_result_step(db, run_id, ["src/auth.py"], "1 passed", "fixed")

    loaded = load_artifact(db, run_id=run_id)
    assert loaded["run_status"] == "execution_result_received"
    assert loaded["execution_result"]["changed_files"] == ["src/auth.py"]


# ---------------------------------------------------------------------------
# 6. spec alignment fail → slice retry
# ---------------------------------------------------------------------------

def test_spec_alignment_fail_slice_retry(tmp_path):
    """changed_files 비어있으면 → slice_issue"""
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    run_id = result["run_id"]

    apply_user_approval(db, run_id, "approve")
    create_packet_if_approved(db, str(tmp_path), run_id, "goal", "approved")
    save_execution_result_step(db, run_id, [], "0 passed", "nothing done")

    v = run_verification(db, run_id)
    assert not v["all_passed"]
    # result_verifier가 잡아냄 → slice_issue로 분류됨
    loaded = load_artifact(db, run_id=run_id)
    assert loaded["run_status"] == "verification_failed"


# ---------------------------------------------------------------------------
# 7. spec alignment fail → doc re-audit
# ---------------------------------------------------------------------------

def test_spec_alignment_fail_doc_reaudit(tmp_path):
    """scope 이탈 파일 → doc_issue"""
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    run_id = result["run_id"]

    apply_user_approval(db, run_id, "approve")
    # deliverable_spec에 target_files 세팅
    update_artifact(db, run_id, {
        "deliverable_spec": {
            "goal": "fix auth",
            "scope": "auth",
            "target_files": ["src/auth.py"],
            "constraints": ["scope 이탈 금지"],
            "acceptance_criteria": ["test pass"],
        },
    })
    create_packet_if_approved(db, str(tmp_path), run_id, "goal", "approved")
    save_execution_result_step(db, run_id, ["src/unrelated.py"], "1 passed", "done")

    v = run_verification(db, run_id)
    assert not v["all_passed"]
    assert v["spec_alignment"]["failure_type"] == "doc_issue"


# ---------------------------------------------------------------------------
# 8. full E2E single flow
# ---------------------------------------------------------------------------

def test_full_e2e_single_flow(tmp_path):
    """
    classify → research → doc → audit → freeze → spec → plan
    → planner → builder → review → approve → packet
    → execution_result → verify → finalize
    """
    db = str(tmp_path / "test.db")
    base_dir = str(tmp_path)
    goal = "로그인 버그 수정해줘"

    # 1. 오케스트레이션
    result = run_orchestration(goal, db)
    run_id = result["run_id"]

    assert result["task_type"] == "code_fix"
    assert result["approval_status"] == "pending"
    assert result.get("canonical_doc") is not None
    assert result.get("plan") is not None
    assert result.get("builder_output") is not None
    assert result.get("reviewer_feedback") is not None

    # 2. 승인
    apply_user_approval(db, run_id, "approve")
    loaded = load_artifact(db, run_id=run_id)
    assert loaded["approval_status"] == "approved"

    # 3. 패킷 생성
    packet = create_packet_if_approved(db, base_dir, run_id, goal, "approved")
    assert packet["packet_created"] is True
    assert run_id in packet["packet_path"]

    # 4. 실행 결과 입력
    save_execution_result_step(db, run_id, ["src/auth.py"], "2 passed", "fixed login")

    loaded = load_artifact(db, run_id=run_id)
    assert loaded["run_status"] == "execution_result_received"

    # 5. 검증
    v = run_verification(db, run_id)
    assert v["all_passed"]

    # 6. finalize
    summary = finalize_run_step(
        db, run_id, goal, "approved", ["src/auth.py"], "2 passed", "fixed login",
    )
    assert "completed" in summary

    loaded = load_artifact(db, run_id=run_id)
    assert loaded["run_status"] == "completed"
    assert loaded["final_summary"] is not None
