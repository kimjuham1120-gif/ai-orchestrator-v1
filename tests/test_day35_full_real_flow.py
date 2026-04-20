"""
Day 35 — Full Real Flow 검증.

stub 모드에서 전체 흐름을 한 번에 통과시키는 smoke test.
각 단계가 올바른 상태를 생성하는지 체크포인트별로 단언.

흐름:
  request → classify → research → initial_doc → cross_audit → canonical_freeze
  → deliverable_spec → backward_plan → planner → builder → 3-layer review
  → approval_prepare → [approve] → packet → execution_result
  → result_verifier → spec_alignment → finalize
"""
from src.orchestrator import (
    run_orchestration,
    create_packet_if_approved,
    save_execution_result_step,
    run_verification,
    finalize_run_step,
)
from src.approval.approval_service import apply_user_approval
from src.store.artifact_store import load_artifact
from pathlib import Path


class TestFullRealFlow:
    """전체 흐름을 단계별 체크포인트로 검증."""

    def test_step1_classify_and_research(self, tmp_path):
        """classify → research_bundle 생성."""
        db = str(tmp_path / "t.db")
        result = run_orchestration("로그인 버그 수정해줘", db)

        assert result["task_type"] == "code_fix", \
            f"classify 실패: task_type={result['task_type']}"
        # research_bundle은 어댑터 없어도 빈 번들로 통과
        assert "research_bundle" in result

    def test_step2_document_layer(self, tmp_path):
        """initial_doc → cross_audit → canonical_freeze."""
        db = str(tmp_path / "t.db")
        result = run_orchestration("로그인 버그 수정해줘", db)

        assert result.get("initial_document") is not None, "initial_document 없음"
        assert result.get("cross_audit_result") is not None, "cross_audit_result 없음"

        canonical = result.get("canonical_doc")
        assert canonical is not None, "canonical_doc 없음"
        assert canonical.get("frozen") is True, \
            f"canonical_frozen=False — cross_audit 실패 가능성: {result.get('cross_audit_result')}"

    def test_step3_planning_layer(self, tmp_path):
        """deliverable_spec → backward_plan → slice_plan."""
        db = str(tmp_path / "t.db")
        result = run_orchestration("로그인 버그 수정해줘", db)

        spec = result.get("deliverable_spec")
        assert spec is not None, "deliverable_spec 없음"
        assert spec.get("goal"), "deliverable_spec.goal 없음"

        slice_plan = result.get("slice_plan")
        assert slice_plan is not None, "slice_plan 없음"
        assert len(slice_plan.get("slices", [])) > 0, "slice_plan.slices 비어있음"

    def test_step4_planner_and_builder(self, tmp_path):
        """planner → builder 출력 확인."""
        db = str(tmp_path / "t.db")
        result = run_orchestration("로그인 버그 수정해줘", db)

        plan = result.get("plan")
        assert plan is not None and len(plan) > 0, "plan 없음"
        assert all("step" in s and "description" in s for s in plan), \
            f"plan 형식 오류: {plan}"

        builder_output = result.get("builder_output")
        assert builder_output is not None and len(builder_output) > 0, "builder_output 없음"
        assert all("step" in s and "action" in s for s in builder_output), \
            f"builder_output 형식 오류: {builder_output}"

    def test_step5_three_layer_review(self, tmp_path):
        """3-layer review — rule_check + llm_review + feedback."""
        db = str(tmp_path / "t.db")
        result = run_orchestration("로그인 버그 수정해줘", db)

        assert result.get("rule_check_result") is not None, "rule_check_result 없음"
        assert result.get("llm_review_result") is not None, "llm_review_result 없음"
        feedback = result.get("reviewer_feedback")
        assert feedback is not None and len(feedback) > 0, "reviewer_feedback 없음"

    def test_step6_approval_gate(self, tmp_path):
        """approval_prepare → waiting_approval 상태."""
        db = str(tmp_path / "t.db")
        result = run_orchestration("로그인 버그 수정해줘", db)

        assert result["run_status"] == "waiting_approval", \
            f"approval_prepare 실패: run_status={result['run_status']}"
        assert result["approval_status"] == "pending", \
            f"approval_status={result['approval_status']}"

    def test_step7_approve_and_packet(self, tmp_path):
        """approve → packet 생성 → packet_ready."""
        db = str(tmp_path / "t.db")
        result = run_orchestration("로그인 버그 수정해줘", db)
        run_id = result["run_id"]

        apply_user_approval(db, run_id, "approve")
        loaded = load_artifact(db, run_id=run_id)
        assert loaded["approval_status"] == "approved", "approve 실패"

        packet_info = create_packet_if_approved(db, str(tmp_path), run_id, "로그인 버그 수정", "approved")
        assert packet_info["packet_created"] is True, \
            f"packet 생성 실패: {packet_info}"

        packet_path = packet_info["packet_path"]
        assert Path(packet_path).exists(), f"packet 파일 없음: {packet_path}"

        # 패킷 파일 내용 확인
        content = Path(packet_path).read_text(encoding="utf-8")
        for field in ["run_id", "goal", "scope", "target_files",
                      "forbidden_actions", "completion_criteria",
                      "test_command", "output_format"]:
            assert field in content, f"packet 필드 누락: {field}"

        loaded = load_artifact(db, run_id=run_id)
        assert loaded["run_status"] == "packet_ready"

    def test_step8_execution_result(self, tmp_path):
        """execution_result 수신 → execution_result_received."""
        db = str(tmp_path / "t.db")
        result = run_orchestration("로그인 버그 수정해줘", db)
        run_id = result["run_id"]
        apply_user_approval(db, run_id, "approve")
        create_packet_if_approved(db, str(tmp_path), run_id, "goal", "approved")

        save_execution_result_step(db, run_id, ["src/auth.py"], "3 passed", "login bug fixed")

        loaded = load_artifact(db, run_id=run_id)
        assert loaded["run_status"] == "execution_result_received"
        assert loaded["execution_result"]["changed_files"] == ["src/auth.py"]
        assert loaded["execution_result"]["test_results"] == "3 passed"

    def test_step9_result_verifier(self, tmp_path):
        """result_verifier — 완전한 결과는 통과."""
        db = str(tmp_path / "t.db")
        result = run_orchestration("로그인 버그 수정해줘", db)
        run_id = result["run_id"]
        apply_user_approval(db, run_id, "approve")
        create_packet_if_approved(db, str(tmp_path), run_id, "goal", "approved")
        save_execution_result_step(db, run_id, ["src/auth.py"], "3 passed", "login bug fixed")

        v = run_verification(db, run_id)

        assert v["result_verification"]["passed"] is True, \
            f"result_verifier 실패: {v['result_verification']['issues']}"

    def test_step10_spec_alignment(self, tmp_path):
        """spec_alignment — scope 이탈 없으면 통과."""
        db = str(tmp_path / "t.db")
        result = run_orchestration("로그인 버그 수정해줘", db)
        run_id = result["run_id"]
        apply_user_approval(db, run_id, "approve")
        create_packet_if_approved(db, str(tmp_path), run_id, "goal", "approved")
        save_execution_result_step(db, run_id, ["src/auth.py"], "3 passed", "login bug fixed")

        v = run_verification(db, run_id)

        assert v["spec_alignment"]["aligned"] is True, \
            f"spec_alignment 실패: {v['spec_alignment']}"
        assert v["all_passed"] is True

    def test_step11_finalize(self, tmp_path):
        """finalize → run_status='completed', final_summary 생성."""
        db = str(tmp_path / "t.db")
        goal = "로그인 버그 수정해줘"
        result = run_orchestration(goal, db)
        run_id = result["run_id"]
        apply_user_approval(db, run_id, "approve")
        create_packet_if_approved(db, str(tmp_path), run_id, goal, "approved")
        save_execution_result_step(db, run_id, ["src/auth.py"], "3 passed", "login bug fixed")
        run_verification(db, run_id)

        summary = finalize_run_step(
            db, run_id, goal, "approved",
            ["src/auth.py"], "3 passed", "login bug fixed"
        )

        assert "completed" in summary
        loaded = load_artifact(db, run_id=run_id)
        assert loaded["run_status"] == "completed"
        assert loaded["final_summary"] is not None
        assert run_id in loaded["final_summary"]

    def test_full_flow_end_to_end(self, tmp_path):
        """전체 흐름 단일 테스트 — 모든 단계를 순서대로."""
        db = str(tmp_path / "t.db")
        base = str(tmp_path)
        goal = "인증 모듈 버그 수정해줘"

        # Step 1~6: orchestration
        result = run_orchestration(goal, db)
        run_id = result["run_id"]
        assert result["task_type"] == "code_fix"
        assert result["approval_status"] == "pending"
        assert result.get("canonical_doc", {}).get("frozen") is True
        assert result.get("plan") is not None
        assert result.get("builder_output") is not None
        assert result.get("reviewer_feedback") is not None

        # Step 7: approve + packet
        apply_user_approval(db, run_id, "approve")
        packet = create_packet_if_approved(db, base, run_id, goal, "approved")
        assert packet["packet_created"] is True
        assert Path(packet["packet_path"]).exists()

        # Step 8: execution result (Cursor handoff 시뮬레이션)
        save_execution_result_step(db, run_id, ["src/auth.py"], "5 passed", "fixed")
        assert load_artifact(db, run_id=run_id)["run_status"] == "execution_result_received"

        # Step 9~10: verify
        v = run_verification(db, run_id)
        assert v["all_passed"], \
            f"검증 실패: verifier={v['result_verification']}, alignment={v['spec_alignment']}"

        # Step 11: finalize
        summary = finalize_run_step(db, run_id, goal, "approved", ["src/auth.py"], "5 passed", "fixed")
        assert "completed" in summary
        assert load_artifact(db, run_id=run_id)["run_status"] == "completed"
