"""Planner 서비스 테스트."""
import os
from unittest.mock import patch
from src.planner.planner_service import run_planner
from src.planner.planner_schema import PLAN_STATUS_CREATED


def test_planner_no_api_key_returns_fake():
    with patch.dict(os.environ, {}, clear=True):
        result, model_id = run_planner("버그 수정해줘", "code_fix")
    assert result.plan_status == PLAN_STATUS_CREATED
    assert len(result.plan) > 0
    assert model_id is None


def test_planner_state_dict_structure():
    with patch.dict(os.environ, {}, clear=True):
        result, _ = run_planner("에러 수정", "code_fix")
    d = result.to_state_dict()
    assert "plan" in d
    assert isinstance(d["plan"], list)
    assert all("step" in s and "description" in s for s in d["plan"])
