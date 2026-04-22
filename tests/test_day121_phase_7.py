"""
Day 121 — Phase 7 · 앱개발 실행 재배치 테스트.

검증 포인트:
1. Phase7Result 구조
2. run_phase_7_from_spec 입력 검증
3. run_phase_7_from_spec 정상 경로 (mock 그래프)
4. handle_approval 유효/무효 decision
5. handle_packet 래핑
6. handle_execution_result 래핑
7. handle_verification 래핑
8. handle_finalize 래핑
9. 그래프 실행 실패 시 안전 처리
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------

def _sample_spec():
    return {
        "goal": "재고관리 시스템 만들어줘",
        "description": "# 재고관리 시스템 초안\n핵심 기능 3개",
        "target_files": [],
        "constraints": ["Phase 3b 기반"],
        "source": "phase_3_target_doc",
    }


def _mock_graph_result():
    """정상적인 그래프 결과 모형."""
    return {
        "plan": [{"step": 1, "action": "design"}],
        "plan_status": "ok",
        "selected_models": {"planner": "openai/gpt-5.4"},
        "builder_output": [{"file": "a.py", "content": "..."}],
        "builder_status": "ok",
        "rule_check_result": {"passed": True},
        "llm_review_result": {"passed": True},
        "reviewer_feedback": [],
        "approval_required": True,
        "approval_status": "pending",
        "approval_reason": "requires_user_approval",
        "run_status": "waiting_approval",
        "last_node": "approval_prepare",
    }


# ===========================================================================
# 1. 결과 구조
# ===========================================================================

class TestPhase7Result:
    def test_to_dict_has_all_keys(self):
        from src.phases.phase_7_app_dev import Phase7Result
        r = Phase7Result()
        d = r.to_dict()
        for key in [
            "status", "run_id", "thread_id",
            "plan", "builder_output", "reviewer_feedback",
            "approval_required", "approval_status", "approval_reason",
            "run_status", "last_node", "error",
        ]:
            assert key in d


# ===========================================================================
# 2. 입력 검증
# ===========================================================================

class TestInputValidation:
    def test_non_dict_spec_fails(self, tmp_path):
        from src.phases.phase_7_app_dev import run_phase_7_from_spec, STATUS_FAILED
        r = run_phase_7_from_spec(
            deliverable_spec="not a dict",
            raw_input="요청",
            db_path=str(tmp_path / "x.db"),
        )
        assert r.status == STATUS_FAILED
        assert "dict" in r.error

    def test_empty_description_fails(self, tmp_path):
        from src.phases.phase_7_app_dev import run_phase_7_from_spec, STATUS_FAILED
        spec = _sample_spec()
        spec["description"] = ""
        r = run_phase_7_from_spec(
            deliverable_spec=spec,
            raw_input="요청",
            db_path=str(tmp_path / "x.db"),
        )
        assert r.status == STATUS_FAILED
        assert "description" in r.error

    def test_whitespace_description_fails(self, tmp_path):
        from src.phases.phase_7_app_dev import run_phase_7_from_spec
        spec = _sample_spec()
        spec["description"] = "   \n  "
        r = run_phase_7_from_spec(
            deliverable_spec=spec,
            raw_input="요청",
            db_path=str(tmp_path / "x.db"),
        )
        assert r.status == "failed"

    def test_empty_raw_input_fails(self, tmp_path):
        from src.phases.phase_7_app_dev import run_phase_7_from_spec
        r = run_phase_7_from_spec(
            deliverable_spec=_sample_spec(),
            raw_input="",
            db_path=str(tmp_path / "x.db"),
        )
        assert r.status == "failed"
        assert "raw_input" in r.error


# ===========================================================================
# 3. 정상 경로 (그래프 mock)
# ===========================================================================

class TestHappyPath:
    def test_successful_phase_7_entry(self, tmp_path):
        from src.phases import phase_7_app_dev as p7

        # build_phase_7_graph를 mock — 즉시 app.invoke 가능하도록
        mock_app = MagicMock()
        mock_app.invoke = MagicMock(return_value=_mock_graph_result())

        with patch("src.graph_flow.build_phase_7_graph", return_value=mock_app):
            r = p7.run_phase_7_from_spec(
                deliverable_spec=_sample_spec(),
                raw_input="재고관리 시스템 만들어줘",
                db_path=str(tmp_path / "x.db"),
            )

            assert r.status == p7.STATUS_OK
            assert r.run_id != ""
            assert r.thread_id != ""
            assert r.approval_required is True
            assert r.approval_status == "pending"
            assert r.run_status == "waiting_approval"
            assert r.plan == [{"step": 1, "action": "design"}]
            assert r.builder_output is not None

    def test_artifact_saved_to_db(self, tmp_path):
        """Phase 7 실행 후 artifact가 DB에 저장됨."""
        from src.phases import phase_7_app_dev as p7
        from src.store.artifact_store import load_artifact

        mock_app = MagicMock()
        mock_app.invoke = MagicMock(return_value=_mock_graph_result())

        db_path = str(tmp_path / "x.db")
        with patch("src.graph_flow.build_phase_7_graph", return_value=mock_app):
            r = p7.run_phase_7_from_spec(
                deliverable_spec=_sample_spec(),
                raw_input="요청",
                db_path=db_path,
                project_id="proj-test-001",
            )

        artifact = load_artifact(db_path, run_id=r.run_id)
        assert artifact is not None
        assert artifact["project_id"] == "proj-test-001"
        assert artifact["phase"] == "phase_7"
        assert artifact["raw_input"] == "요청"
        assert artifact["deliverable_spec"] == _sample_spec()
        assert artifact["run_status"] == "waiting_approval"

    def test_graph_invoked_with_correct_state(self, tmp_path):
        """그래프가 올바른 입력 state로 호출됨."""
        from src.phases import phase_7_app_dev as p7

        mock_app = MagicMock()
        mock_app.invoke = MagicMock(return_value=_mock_graph_result())

        with patch("src.graph_flow.build_phase_7_graph", return_value=mock_app):
            p7.run_phase_7_from_spec(
                deliverable_spec=_sample_spec(),
                raw_input="특별한_요청",
                db_path=str(tmp_path / "x.db"),
                task_type="code_fix",
            )

        call_args = mock_app.invoke.call_args
        state = call_args[0][0]
        assert state["raw_input"] == "특별한_요청"
        assert state["task_type"] == "code_fix"
        assert state["deliverable_spec"] == _sample_spec()


# ===========================================================================
# 4. 그래프 실행 실패
# ===========================================================================

class TestGraphFailure:
    def test_graph_invoke_exception_caught(self, tmp_path):
        """그래프 실행 중 예외 → Phase7Result(failed) 반환."""
        from src.phases import phase_7_app_dev as p7

        mock_app = MagicMock()
        mock_app.invoke = MagicMock(side_effect=RuntimeError("planner died"))

        with patch("src.graph_flow.build_phase_7_graph", return_value=mock_app):
            r = p7.run_phase_7_from_spec(
                deliverable_spec=_sample_spec(),
                raw_input="요청",
                db_path=str(tmp_path / "x.db"),
            )

        assert r.status == "failed"
        assert "planner died" in r.error
        assert r.run_id != ""  # run_id는 생성됨 (디버깅 위해)


# ===========================================================================
# 5. handle_approval
# ===========================================================================

class TestHandleApproval:
    def test_approve_success(self, tmp_path):
        from src.phases import phase_7_app_dev as p7

        with patch("src.approval.approval_service.apply_user_approval") as mock_approve:
            result = p7.handle_approval(
                db_path=str(tmp_path / "x.db"),
                run_id="run-001",
                decision="approve",
            )

            assert result["ok"] is True
            assert result["approval_status"] == "approve"
            assert result["error"] is None
            mock_approve.assert_called_once()

    def test_reject_success(self, tmp_path):
        from src.phases import phase_7_app_dev as p7

        with patch("src.approval.approval_service.apply_user_approval"):
            result = p7.handle_approval(
                db_path=str(tmp_path / "x.db"),
                run_id="run-001",
                decision="reject",
            )

            assert result["ok"] is True
            assert result["approval_status"] == "reject"

    @pytest.mark.parametrize("bad_decision", ["unknown", "yes", "no", "cancel", ""])
    def test_invalid_decision_rejected(self, tmp_path, bad_decision):
        from src.phases import phase_7_app_dev as p7
        result = p7.handle_approval(
            db_path=str(tmp_path / "x.db"),
            run_id="run-001",
            decision=bad_decision,
        )
        assert result["ok"] is False
        assert result["error"] is not None

    def test_case_insensitive(self, tmp_path):
        from src.phases import phase_7_app_dev as p7
        with patch("src.approval.approval_service.apply_user_approval"):
            result = p7.handle_approval(
                db_path=str(tmp_path / "x.db"),
                run_id="run-001",
                decision="APPROVE",
            )
            assert result["ok"] is True

    def test_exception_caught(self, tmp_path):
        from src.phases import phase_7_app_dev as p7
        with patch(
            "src.approval.approval_service.apply_user_approval",
            side_effect=RuntimeError("db down"),
        ):
            result = p7.handle_approval(
                db_path=str(tmp_path / "x.db"),
                run_id="run-001",
                decision="approve",
            )
            assert result["ok"] is False
            assert "db down" in result["error"]


# ===========================================================================
# 6. handle_packet
# ===========================================================================

class TestHandlePacket:
    def test_packet_success_when_approved(self, tmp_path):
        from src.phases import phase_7_app_dev as p7
        from src.store.artifact_store import save_artifact

        db_path = str(tmp_path / "x.db")
        # 먼저 artifact 저장 (approval_status=approved)
        save_artifact(db_path, {
            "run_id": "run-001",
            "raw_input": "요청",
            "approval_status": "approved",
        })

        mock_result = {
            "packet_created": True,
            "packet_path": "/tmp/packet.json",
            "error": None,
        }
        with patch(
            "src.orchestrator.create_packet_if_approved",
            return_value=mock_result,
        ) as mock_create:
            result = p7.handle_packet(db_path, "run-001", base_dir=".")
            assert result == mock_result
            mock_create.assert_called_once()

    def test_packet_run_not_found(self, tmp_path):
        from src.phases import phase_7_app_dev as p7
        result = p7.handle_packet(
            db_path=str(tmp_path / "empty.db"),
            run_id="nonexistent",
        )
        assert result["packet_created"] is False
        assert "찾을 수 없음" in result["error"]

    def test_packet_exception_caught(self, tmp_path):
        from src.phases import phase_7_app_dev as p7
        from src.store.artifact_store import save_artifact

        db_path = str(tmp_path / "x.db")
        save_artifact(db_path, {"run_id": "run-001", "raw_input": "요청"})

        with patch(
            "src.orchestrator.create_packet_if_approved",
            side_effect=RuntimeError("disk full"),
        ):
            result = p7.handle_packet(db_path, "run-001")
            assert result["packet_created"] is False
            assert "disk full" in result["error"]


# ===========================================================================
# 7. handle_execution_result
# ===========================================================================

class TestHandleExecutionResult:
    def test_success(self, tmp_path):
        from src.phases import phase_7_app_dev as p7

        with patch("src.orchestrator.save_execution_result_step") as mock_save:
            result = p7.handle_execution_result(
                db_path=str(tmp_path / "x.db"),
                run_id="run-001",
                changed_files=["a.py", "b.py"],
                test_results="3 passed",
                run_log="ok",
            )
            assert result["ok"] is True
            mock_save.assert_called_once()

    def test_none_values_converted_to_defaults(self, tmp_path):
        from src.phases import phase_7_app_dev as p7

        with patch("src.orchestrator.save_execution_result_step") as mock_save:
            p7.handle_execution_result(
                db_path=str(tmp_path / "x.db"),
                run_id="run-001",
                changed_files=None,
                test_results=None,
                run_log=None,
            )
            # None이 빈 값으로 변환되어 전달
            call_kwargs = mock_save.call_args.kwargs
            assert call_kwargs["changed_files"] == []
            assert call_kwargs["test_results"] == ""
            assert call_kwargs["run_log"] == ""

    def test_exception_caught(self, tmp_path):
        from src.phases import phase_7_app_dev as p7
        with patch(
            "src.orchestrator.save_execution_result_step",
            side_effect=RuntimeError("db fail"),
        ):
            result = p7.handle_execution_result(
                db_path=str(tmp_path / "x.db"),
                run_id="run-001",
                changed_files=[],
                test_results="",
                run_log="",
            )
            assert result["ok"] is False
            assert "db fail" in result["error"]


# ===========================================================================
# 8. handle_verification
# ===========================================================================

class TestHandleVerification:
    def test_all_passed(self, tmp_path):
        from src.phases import phase_7_app_dev as p7
        mock_result = {
            "result_verification": {"passed": True, "issues": []},
            "spec_alignment": {"aligned": True},
            "all_passed": True,
        }
        with patch(
            "src.orchestrator.run_verification",
            return_value=mock_result,
        ):
            result = p7.handle_verification(
                db_path=str(tmp_path / "x.db"),
                run_id="run-001",
            )
            assert result["ok"] is True
            assert result["all_passed"] is True

    def test_failure_returns_not_all_passed(self, tmp_path):
        from src.phases import phase_7_app_dev as p7
        mock_result = {
            "result_verification": {"passed": False, "issues": ["문제"]},
            "spec_alignment": {"aligned": False, "failure_type": "slice_issue"},
            "all_passed": False,
        }
        with patch(
            "src.orchestrator.run_verification",
            return_value=mock_result,
        ):
            result = p7.handle_verification(
                db_path=str(tmp_path / "x.db"),
                run_id="run-001",
            )
            assert result["ok"] is True
            assert result["all_passed"] is False
            assert result["spec_alignment"].get("failure_type") == "slice_issue"

    def test_exception_caught(self, tmp_path):
        from src.phases import phase_7_app_dev as p7
        with patch(
            "src.orchestrator.run_verification",
            side_effect=RuntimeError("verify down"),
        ):
            result = p7.handle_verification(
                db_path=str(tmp_path / "x.db"),
                run_id="run-001",
            )
            assert result["ok"] is False
            assert "verify down" in result["error"]


# ===========================================================================
# 9. handle_finalize
# ===========================================================================

class TestHandleFinalize:
    def test_success(self, tmp_path):
        from src.phases import phase_7_app_dev as p7
        from src.store.artifact_store import save_artifact

        db_path = str(tmp_path / "x.db")
        save_artifact(db_path, {
            "run_id": "run-001",
            "raw_input": "요청",
            "approval_status": "approved",
            "execution_result": {
                "changed_files": ["a.py"],
                "test_results": "3 passed",
                "run_log": "ok",
            },
        })

        with patch(
            "src.orchestrator.finalize_run_step",
            return_value="[completed] ...",
        ) as mock_finalize:
            result = p7.handle_finalize(db_path, "run-001")
            assert result["ok"] is True
            assert "completed" in result["summary"]
            mock_finalize.assert_called_once()

    def test_run_not_found(self, tmp_path):
        from src.phases import phase_7_app_dev as p7
        result = p7.handle_finalize(
            db_path=str(tmp_path / "empty.db"),
            run_id="nonexistent",
        )
        assert result["ok"] is False
        assert "찾을 수 없음" in result["error"]

    def test_exception_caught(self, tmp_path):
        from src.phases import phase_7_app_dev as p7
        from src.store.artifact_store import save_artifact

        db_path = str(tmp_path / "x.db")
        save_artifact(db_path, {"run_id": "run-001", "raw_input": "요청"})

        with patch(
            "src.orchestrator.finalize_run_step",
            side_effect=RuntimeError("finalize down"),
        ):
            result = p7.handle_finalize(db_path, "run-001")
            assert result["ok"] is False
            assert "finalize down" in result["error"]


# ===========================================================================
# 10. 전체 사이클 스모크
# ===========================================================================

class TestFullCycleSmoke:
    def test_spec_to_approval_ready(self, tmp_path):
        """Phase 6 spec → Phase 7 진입 → 승인 대기 상태까지 전체 검증."""
        from src.phases import phase_7_app_dev as p7
        from src.store.artifact_store import load_artifact

        mock_app = MagicMock()
        mock_app.invoke = MagicMock(return_value=_mock_graph_result())

        db_path = str(tmp_path / "x.db")
        with patch("src.graph_flow.build_phase_7_graph", return_value=mock_app):
            # Phase 7 진입
            r = p7.run_phase_7_from_spec(
                deliverable_spec=_sample_spec(),
                raw_input="요청",
                db_path=db_path,
                project_id="proj-full-001",
            )

        assert r.status == "ok"
        assert r.approval_required is True

        # DB에서 확인
        artifact = load_artifact(db_path, run_id=r.run_id)
        assert artifact["project_id"] == "proj-full-001"
        assert artifact["phase"] == "phase_7"
