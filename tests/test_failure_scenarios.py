"""v1 실패 시나리오 테스트 — 승인 거절, 불완전 결과, 설정 오류."""
import os
from unittest.mock import patch, MagicMock
import pytest
import httpx

from src.orchestrator import (
    run_orchestration,
    create_packet_if_approved,
    save_execution_result_step,
    run_verification,
)
from src.approval.approval_service import apply_user_approval
from src.store.artifact_store import load_artifact


# ---------------------------------------------------------------------------
# 1. 승인 거절
# ---------------------------------------------------------------------------

def test_rejection_sets_rejected_status(tmp_path):
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    apply_user_approval(db, result["run_id"], "reject")
    loaded = load_artifact(db, run_id=result["run_id"])
    assert loaded["approval_status"] == "rejected"
    assert loaded["run_status"] == "rejected"


def test_rejection_blocks_packet(tmp_path):
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    apply_user_approval(db, result["run_id"], "reject")
    packet = create_packet_if_approved(db, str(tmp_path), result["run_id"], "goal", "rejected")
    assert packet["packet_created"] is False


def test_rejection_does_not_complete(tmp_path):
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    apply_user_approval(db, result["run_id"], "reject")
    loaded = load_artifact(db, run_id=result["run_id"])
    assert loaded["run_status"] != "completed"


# ---------------------------------------------------------------------------
# 2. 불완전 execution_result
# ---------------------------------------------------------------------------

def test_empty_changed_files_fails_verification(tmp_path):
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    run_id = result["run_id"]
    apply_user_approval(db, run_id, "approve")
    create_packet_if_approved(db, str(tmp_path), run_id, "goal", "approved")
    save_execution_result_step(db, run_id, [], "1 passed", "fixed")
    v = run_verification(db, run_id)
    assert not v["all_passed"]


def test_empty_test_results_fails_verification(tmp_path):
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    run_id = result["run_id"]
    apply_user_approval(db, run_id, "approve")
    create_packet_if_approved(db, str(tmp_path), run_id, "goal", "approved")
    save_execution_result_step(db, run_id, ["a.py"], "", "fixed")
    v = run_verification(db, run_id)
    assert not v["all_passed"]


def test_empty_run_log_fails_verification(tmp_path):
    db = str(tmp_path / "test.db")
    result = run_orchestration("버그 수정해줘", db)
    run_id = result["run_id"]
    apply_user_approval(db, run_id, "approve")
    create_packet_if_approved(db, str(tmp_path), run_id, "goal", "approved")
    save_execution_result_step(db, run_id, ["a.py"], "1 passed", "")
    v = run_verification(db, run_id)
    assert not v["all_passed"]


# ---------------------------------------------------------------------------
# 3. unsupported 입력
# ---------------------------------------------------------------------------

def test_unsupported_stops_immediately(tmp_path):
    db = str(tmp_path / "test.db")
    result = run_orchestration("오늘 날씨 알려줘", db)
    assert result["task_type"] == "unsupported"
    assert result["run_status"] == "failed"
    assert result["error"] == "unsupported_task_type"


def test_unsupported_no_plan_or_builder(tmp_path):
    db = str(tmp_path / "test.db")
    result = run_orchestration("주식 추천해줘", db)
    assert result.get("plan") is None
    assert result.get("builder_output") is None


def test_unsupported_blocks_packet(tmp_path):
    db = str(tmp_path / "test.db")
    result = run_orchestration("맛집 알려줘", db)
    packet = create_packet_if_approved(db, str(tmp_path), result["run_id"], "goal", "not_needed")
    assert packet["packet_created"] is False


# ---------------------------------------------------------------------------
# 4. API 호출 실패 시 예외 전파
# ---------------------------------------------------------------------------

def test_api_failure_raises_exception(tmp_path):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=MagicMock()
    )
    env = {**os.environ, "OPENROUTER_API_KEY": "sk-invalid"}
    with patch.dict(os.environ, env, clear=True):
        with patch("httpx.post", return_value=mock_resp):
            with pytest.raises(Exception):
                run_orchestration("버그 수정해줘", str(tmp_path / "test.db"))
