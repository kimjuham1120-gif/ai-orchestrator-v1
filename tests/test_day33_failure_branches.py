"""
Day 33 — spec_alignment 실패 분기 2개 + 복구 경로 검증.

시나리오 A: slice_issue
  - 상황: Cursor가 아무것도 안 했거나 결과를 잘못 입력
  - 재현: changed_files=[] (또는 test_results="")
  - 기대: failure_type="slice_issue"
  - 복구: retry_current_slice() → 동일 slice 재실행 → 재승인 대기

시나리오 B: doc_issue
  - 상황: Cursor가 scope 밖 파일을 수정
  - 재현: changed_files=["src/unrelated.py"], target_files=["src/auth.py"]
  - 기대: failure_type="doc_issue"
  - 복구: reaudit_doc(patched_target_files=["src/unrelated.py"]) → 재동결 → 재실행
"""
import pytest
from src.orchestrator import (
    run_orchestration,
    create_packet_if_approved,
    save_execution_result_step,
    run_verification,
    retry_current_slice,
    reaudit_doc,
)
from src.approval.approval_service import apply_user_approval
from src.store.artifact_store import load_artifact, update_artifact


# ---------------------------------------------------------------------------
# 공통 픽스처: approval → packet까지 완료된 run
# ---------------------------------------------------------------------------

def _setup_approved_run(db_path: str, base_dir: str, target_files=None) -> str:
    result = run_orchestration("로그인 버그 수정해줘", db_path)
    run_id = result["run_id"]
    apply_user_approval(db_path, run_id, "approve")

    if target_files is not None:
        existing_spec = load_artifact(db_path, run_id=run_id).get("deliverable_spec") or {}
        update_artifact(db_path, run_id, {
            "deliverable_spec": {**existing_spec, "target_files": target_files}
        })

    create_packet_if_approved(db_path, base_dir, run_id, "로그인 버그 수정", "approved")
    return run_id


# ===========================================================================
# 시나리오 A — slice_issue
# ===========================================================================

class TestSliceIssueBranch:
    def test_empty_changed_files_produces_slice_issue(self, tmp_path):
        """changed_files=[] → failure_type='slice_issue'."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path))
        save_execution_result_step(db, run_id, [], "0 passed", "nothing changed")

        v = run_verification(db, run_id)

        assert not v["all_passed"]
        assert v["spec_alignment"]["failure_type"] == "slice_issue"

    def test_empty_test_results_produces_slice_issue(self, tmp_path):
        """test_results='' → failure_type='slice_issue'."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path))
        save_execution_result_step(db, run_id, ["src/auth.py"], "", "did something")

        v = run_verification(db, run_id)

        assert not v["all_passed"]
        assert v["spec_alignment"]["failure_type"] == "slice_issue"

    def test_empty_run_log_produces_slice_issue(self, tmp_path):
        """run_log='' → failure_type='slice_issue'."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path))
        save_execution_result_step(db, run_id, ["src/auth.py"], "1 passed", "")

        v = run_verification(db, run_id)

        assert not v["all_passed"]
        assert v["spec_alignment"]["failure_type"] == "slice_issue"

    def test_slice_issue_state_is_verification_failed(self, tmp_path):
        """slice_issue 후 run_status='verification_failed'."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path))
        save_execution_result_step(db, run_id, [], "", "")
        run_verification(db, run_id)

        loaded = load_artifact(db, run_id=run_id)
        assert loaded["run_status"] == "verification_failed"

    def test_retry_slice_resets_execution_result(self, tmp_path):
        """retry_current_slice() → execution_result=None, 상태 초기화."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path))
        save_execution_result_step(db, run_id, [], "0 passed", "nothing")
        run_verification(db, run_id)

        updated = retry_current_slice(db, run_id)

        # 실행 결과 초기화 확인
        assert updated.get("execution_result") is None
        assert updated.get("result_verification") is None
        assert updated.get("spec_alignment") is None

    def test_retry_slice_requeues_to_approval(self, tmp_path):
        """retry_current_slice() → 같은 slice 재실행 → approval_status='pending'."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path))
        save_execution_result_step(db, run_id, [], "0 passed", "nothing")
        run_verification(db, run_id)

        updated = retry_current_slice(db, run_id)

        # 재실행 후 승인 대기로 돌아옴
        assert updated.get("approval_status") == "pending"
        assert updated.get("plan") is not None
        assert updated.get("builder_output") is not None

    def test_retry_slice_does_not_advance_index(self, tmp_path):
        """retry는 slice index를 advance하지 않는다."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path))
        before_idx = load_artifact(db, run_id=run_id).get("current_slice_index", 0)

        save_execution_result_step(db, run_id, [], "0 passed", "nothing")
        run_verification(db, run_id)
        retry_current_slice(db, run_id)

        after_idx = load_artifact(db, run_id=run_id).get("current_slice_index", 0)
        assert after_idx == before_idx  # 동일 인덱스 유지


# ===========================================================================
# 시나리오 B — doc_issue
# ===========================================================================

class TestDocIssueBranch:
    def test_scope_drift_produces_doc_issue(self, tmp_path):
        """target_files=['src/auth.py'], changed=['src/unrelated.py'] → doc_issue."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path), target_files=["src/auth.py"])
        save_execution_result_step(db, run_id, ["src/unrelated.py"], "1 passed", "done")

        v = run_verification(db, run_id)

        assert not v["all_passed"]
        assert v["spec_alignment"]["failure_type"] == "doc_issue"
        assert "범위 이탈" in v["spec_alignment"]["mismatches"][0]

    def test_multiple_out_of_scope_files(self, tmp_path):
        """여러 파일이 범위를 이탈해도 doc_issue."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path), target_files=["src/auth.py"])
        save_execution_result_step(
            db, run_id,
            ["src/unrelated.py", "src/another.py"],
            "1 passed", "done"
        )

        v = run_verification(db, run_id)

        assert v["spec_alignment"]["failure_type"] == "doc_issue"

    def test_doc_issue_state_is_verification_failed(self, tmp_path):
        """doc_issue 후 run_status='verification_failed'."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path), target_files=["src/auth.py"])
        save_execution_result_step(db, run_id, ["src/unrelated.py"], "1 passed", "done")
        run_verification(db, run_id)

        loaded = load_artifact(db, run_id=run_id)
        assert loaded["run_status"] == "verification_failed"

    def test_reaudit_doc_updates_target_files(self, tmp_path):
        """reaudit_doc() → deliverable_spec.target_files 교정됨."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path), target_files=["src/auth.py"])
        save_execution_result_step(db, run_id, ["src/unrelated.py"], "1 passed", "done")
        run_verification(db, run_id)

        updated = reaudit_doc(db, run_id, patched_target_files=["src/unrelated.py"])

        spec = updated.get("deliverable_spec") or {}
        assert "src/unrelated.py" in spec.get("target_files", [])

    def test_reaudit_doc_refreezes_canonical(self, tmp_path):
        """reaudit_doc() → canonical_doc 재동결."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path), target_files=["src/auth.py"])
        save_execution_result_step(db, run_id, ["src/unrelated.py"], "1 passed", "done")
        run_verification(db, run_id)

        updated = reaudit_doc(db, run_id, patched_target_files=["src/unrelated.py"])

        canonical = updated.get("canonical_doc") or {}
        assert canonical.get("frozen") is True
        # version이 증가해야 함
        assert canonical.get("version", 1) >= 2

    def test_reaudit_doc_clears_old_verification(self, tmp_path):
        """reaudit_doc() → 이전 검증 결과 초기화."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path), target_files=["src/auth.py"])
        save_execution_result_step(db, run_id, ["src/unrelated.py"], "1 passed", "done")
        run_verification(db, run_id)

        updated = reaudit_doc(db, run_id, patched_target_files=["src/unrelated.py"])

        assert updated.get("execution_result") is None
        assert updated.get("result_verification") is None
        assert updated.get("spec_alignment") is None

    def test_reaudit_doc_auto_fills_from_changed_files(self, tmp_path):
        """patched_target_files=None → execution_result.changed_files로 자동 채움."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path), target_files=["src/auth.py"])
        save_execution_result_step(db, run_id, ["src/unrelated.py"], "1 passed", "done")
        run_verification(db, run_id)

        updated = reaudit_doc(db, run_id)  # patched_target_files=None

        spec = updated.get("deliverable_spec") or {}
        assert "src/unrelated.py" in spec.get("target_files", [])

    def test_reaudit_doc_fails_if_no_files_available(self, tmp_path):
        """patched_target_files=None이고 changed_files도 없으면 ValueError."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path), target_files=["src/auth.py"])
        # execution_result 없이 직접 reaudit 시도
        save_execution_result_step(db, run_id, [], "0 passed", "nothing")
        run_verification(db, run_id)

        with pytest.raises(ValueError, match="비어있음"):
            reaudit_doc(db, run_id, patched_target_files=None)

    def test_reaudit_then_reverify_passes(self, tmp_path):
        """reaudit_doc() 후 올바른 결과 재입력 → 검증 통과."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path), target_files=["src/auth.py"])
        save_execution_result_step(db, run_id, ["src/unrelated.py"], "1 passed", "done")
        run_verification(db, run_id)

        # target_files 교정
        reaudit_doc(db, run_id, patched_target_files=["src/unrelated.py"])

        # 재승인 + 재패킷
        apply_user_approval(db, run_id, "approve")
        create_packet_if_approved(db, str(tmp_path), run_id, "재시도", "approved")

        # 교정된 파일로 재실행 결과 입력
        save_execution_result_step(db, run_id, ["src/unrelated.py"], "1 passed", "fixed")
        v = run_verification(db, run_id)

        assert v["all_passed"]


# ===========================================================================
# slice_issue vs doc_issue 분류 경계 케이스
# ===========================================================================

class TestFailureTypeClassification:
    def test_changed_files_empty_is_always_slice_issue(self, tmp_path):
        """changed_files=[] 이면 spec 유무에 관계없이 slice_issue."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path), target_files=["src/auth.py"])
        save_execution_result_step(db, run_id, [], "1 passed", "done")
        run_verification(db, run_id)

        loaded = load_artifact(db, run_id=run_id)
        assert loaded["spec_alignment"]["failure_type"] == "slice_issue"

    def test_in_scope_files_passes_doc_check(self, tmp_path):
        """changed_files가 target_files 내에 있으면 doc_issue 아님."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path), target_files=["src/auth.py"])
        save_execution_result_step(db, run_id, ["src/auth.py"], "1 passed", "fixed")

        v = run_verification(db, run_id)

        assert v["all_passed"]
        assert v["spec_alignment"]["failure_type"] is None

    def test_no_target_files_in_spec_skips_scope_check(self, tmp_path):
        """spec.target_files=[] 이면 어떤 파일이든 scope 체크 건너뜀."""
        db = str(tmp_path / "t.db")
        run_id = _setup_approved_run(db, str(tmp_path), target_files=[])
        save_execution_result_step(db, run_id, ["src/any_file.py"], "1 passed", "done")

        v = run_verification(db, run_id)

        assert v["all_passed"]
