"""API 연결 경로 검증 — v1 환경변수 기준."""
import os
from unittest.mock import patch, MagicMock
import pytest
import httpx

from src.planner.planner_service import run_planner
from src.builder.builder_service import run_builder
from src.planner.planner_schema import PLAN_STATUS_CREATED
from src.builder.builder_schema import BUILDER_STATUS_CREATED


def _make_mock_response(content: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


_PLANNER_RESP = "1. 문제 파악\n2. 수정 대상 확인\n3. 범위 고정"
_BUILDER_RESP = "1. src/auth.py 수정\n2. 테스트 포인트 정리"


def test_planner_fake_without_api_key():
    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        result, model_id = run_planner("버그 수정", "code_fix")
    assert result.plan_status == PLAN_STATUS_CREATED
    assert model_id is None


def test_builder_fake_without_api_key():
    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        result, model_id = run_builder("버그 수정", "code_fix", [])
    assert result.builder_status == BUILDER_STATUS_CREATED
    assert model_id is None


def test_planner_returns_model_id_with_key():
    env = {**os.environ, "OPENROUTER_API_KEY": "sk-test"}
    with patch.dict(os.environ, env, clear=True):
        with patch("httpx.post", return_value=_make_mock_response(_PLANNER_RESP)):
            result, model_id = run_planner("버그 수정", "code_fix")
    assert result.plan_status == PLAN_STATUS_CREATED
    assert model_id is not None
    assert len(model_id) > 0


def test_builder_returns_model_id_with_key():
    env = {**os.environ, "OPENROUTER_API_KEY": "sk-test"}
    with patch.dict(os.environ, env, clear=True):
        with patch("httpx.post", return_value=_make_mock_response(_BUILDER_RESP)):
            result, model_id = run_builder("버그 수정", "code_fix", [])
    assert result.builder_status == BUILDER_STATUS_CREATED
    assert model_id is not None


def test_api_key_present_but_call_fails():
    """API key 있고 호출 실패 → 예외 전파 (fake 우회 안 됨)"""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401 Unauthorized", request=MagicMock(), response=MagicMock()
    )
    env = {**os.environ, "OPENROUTER_API_KEY": "sk-invalid"}
    with patch.dict(os.environ, env, clear=True):
        with patch("httpx.post", return_value=mock_resp):
            with pytest.raises(Exception):
                run_planner("버그 수정", "code_fix")


def test_planner_default_model():
    from src.planner.planner_config import get_planner_model, DEFAULT_PLANNER_MODEL
    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_PLANNER_MODEL"}
    env["OPENROUTER_API_KEY"] = "sk-test"
    with patch.dict(os.environ, env, clear=True):
        model = get_planner_model()
    assert model == DEFAULT_PLANNER_MODEL


def test_builder_default_model():
    from src.builder.builder_config import get_builder_model, DEFAULT_BUILDER_MODEL
    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_BUILDER_MODEL"}
    env["OPENROUTER_API_KEY"] = "sk-test"
    with patch.dict(os.environ, env, clear=True):
        model = get_builder_model()
    assert model == DEFAULT_BUILDER_MODEL
