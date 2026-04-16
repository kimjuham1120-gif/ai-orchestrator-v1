"""planner/builder payload 옵션 검증 — v1 환경변수 기준."""
import os
from unittest.mock import patch, MagicMock


def _mock_response(content: str) -> MagicMock:
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json.return_value = {"choices": [{"message": {"content": content}}]}
    return m


_PLAN_RESP = "1. 문제 파악\n2. 수정 대상 확인\n3. 범위 고정"
_BUILD_RESP = "1. src/auth.py 수정\n2. 테스트 포인트 정리"


def test_planner_payload_contains_reasoning():
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["payload"] = json
        return _mock_response(_PLAN_RESP)

    env = {**os.environ, "OPENROUTER_API_KEY": "sk-test"}
    with patch.dict(os.environ, env, clear=True):
        with patch("httpx.post", side_effect=fake_post):
            from src.planner.planner_service import run_planner
            run_planner("버그 수정", "code_fix")

    assert "reasoning" in captured["payload"]
    assert "effort" in captured["payload"]["reasoning"]


def test_planner_reasoning_default_medium():
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["payload"] = json
        return _mock_response(_PLAN_RESP)

    env = {k: v for k, v in os.environ.items()
           if k not in ("OPENROUTER_API_KEY", "OPENROUTER_PLANNER_REASONING_EFFORT")}
    env["OPENROUTER_API_KEY"] = "sk-test"
    with patch.dict(os.environ, env, clear=True):
        with patch("httpx.post", side_effect=fake_post):
            from src.planner.planner_service import run_planner
            run_planner("버그 수정", "code_fix")

    assert captured["payload"]["reasoning"]["effort"] == "medium"


def test_planner_reasoning_custom_value():
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["payload"] = json
        return _mock_response(_PLAN_RESP)

    env = {**os.environ, "OPENROUTER_API_KEY": "sk-test",
           "OPENROUTER_PLANNER_REASONING_EFFORT": "high"}
    with patch.dict(os.environ, env, clear=True):
        with patch("httpx.post", side_effect=fake_post):
            from src.planner.planner_service import run_planner
            run_planner("버그 수정", "code_fix")

    assert captured["payload"]["reasoning"]["effort"] == "high"


def test_builder_payload_contains_verbosity():
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["payload"] = json
        return _mock_response(_BUILD_RESP)

    env = {**os.environ, "OPENROUTER_API_KEY": "sk-test"}
    with patch.dict(os.environ, env, clear=True):
        with patch("httpx.post", side_effect=fake_post):
            from src.builder.builder_service import run_builder
            run_builder("버그 수정", "code_fix", [])

    assert "verbosity" in captured["payload"]


def test_builder_verbosity_default_high():
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["payload"] = json
        return _mock_response(_BUILD_RESP)

    env = {k: v for k, v in os.environ.items()
           if k not in ("OPENROUTER_API_KEY", "OPENROUTER_BUILDER_VERBOSITY")}
    env["OPENROUTER_API_KEY"] = "sk-test"
    with patch.dict(os.environ, env, clear=True):
        with patch("httpx.post", side_effect=fake_post):
            from src.builder.builder_service import run_builder
            run_builder("버그 수정", "code_fix", [])

    assert captured["payload"]["verbosity"] == "high"


def test_planner_uses_correct_model_env():
    """OPENROUTER_PLANNER_MODEL 환경변수가 payload에 반영됨"""
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["payload"] = json
        return _mock_response(_PLAN_RESP)

    env = {**os.environ, "OPENROUTER_API_KEY": "sk-test",
           "OPENROUTER_PLANNER_MODEL": "custom/model-v2"}
    with patch.dict(os.environ, env, clear=True):
        with patch("httpx.post", side_effect=fake_post):
            from src.planner.planner_service import run_planner
            run_planner("버그 수정", "code_fix")

    assert captured["payload"]["model"] == "custom/model-v2"


def test_builder_uses_correct_model_env():
    """OPENROUTER_BUILDER_MODEL 환경변수가 payload에 반영됨"""
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["payload"] = json
        return _mock_response(_BUILD_RESP)

    env = {**os.environ, "OPENROUTER_API_KEY": "sk-test",
           "OPENROUTER_BUILDER_MODEL": "anthropic/claude-4"}
    with patch.dict(os.environ, env, clear=True):
        with patch("httpx.post", side_effect=fake_post):
            from src.builder.builder_service import run_builder
            run_builder("버그 수정", "code_fix", [])

    assert captured["payload"]["model"] == "anthropic/claude-4"
