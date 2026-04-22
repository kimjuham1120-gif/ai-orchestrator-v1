"""
Day 57~64 — OpenRouter 유료 모델 전환 검증 테스트.

정책:
  - 실 네트워크 호출 금지 (monkeypatch / mock 전용)
  - 기존 231개 테스트에 추가
  - artifact_store 스키마 변경 없음
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# planner_config 테스트
# ===========================================================================

class TestPlannerConfig:
    def test_default_model(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_PLANNER_MODEL", raising=False)
        from src.planner.planner_config import get_planner_model, DEFAULT_PLANNER_MODEL
        assert get_planner_model() == DEFAULT_PLANNER_MODEL

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_PLANNER_MODEL", "anthropic/claude-sonnet-4-5")
        from src.planner.planner_config import get_planner_model
        assert get_planner_model() == "anthropic/claude-sonnet-4-5"

    def test_reasoning_effort_default_medium(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_PLANNER_REASONING_EFFORT", raising=False)
        from src.planner.planner_config import get_reasoning_effort
        assert get_reasoning_effort() == "medium"

    def test_reasoning_effort_override(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_PLANNER_REASONING_EFFORT", "high")
        from src.planner.planner_config import get_reasoning_effort
        assert get_reasoning_effort() == "high"

    def test_invalid_reasoning_effort_falls_back(self, monkeypatch):
        """잘못된 effort 값 → 기본값 medium으로 fallback."""
        monkeypatch.setenv("OPENROUTER_PLANNER_REASONING_EFFORT", "ultra")
        from src.planner.planner_config import get_reasoning_effort
        assert get_reasoning_effort() == "medium"

    def test_paid_model_reflected_in_payload(self, monkeypatch):
        """유료 모델 설정 시 API payload에 반영."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("OPENROUTER_PLANNER_MODEL", "anthropic/claude-sonnet-4-5")
        captured = {}

        def fake_post(url, json, headers, timeout):
            captured["model"] = json.get("model")
            m = MagicMock()
            m.raise_for_status = MagicMock()
            m.json.return_value = {"choices": [{"message": {"content": "1. step one\n2. step two"}}]}
            return m

        import httpx
        monkeypatch.setattr(httpx, "post", fake_post)
        from src.planner.planner_service import run_planner
        run_planner("버그 수정", "code_fix")
        assert captured["model"] == "anthropic/claude-sonnet-4-5"

    def test_no_api_key_returns_stub(self, monkeypatch):
        """API key 없으면 모델 설정 무관하게 stub."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_PLANNER_MODEL", "anthropic/claude-sonnet-4-5")
        from src.planner.planner_service import run_planner
        from src.planner.planner_schema import PLAN_STATUS_CREATED
        result, model_id = run_planner("버그 수정", "code_fix")
        assert result.plan_status == PLAN_STATUS_CREATED
        assert model_id is None


# ===========================================================================
# builder_config 테스트
# ===========================================================================

class TestBuilderConfig:
    def test_default_model(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_BUILDER_MODEL", raising=False)
        from src.builder.builder_config import get_builder_model, DEFAULT_BUILDER_MODEL
        assert get_builder_model() == DEFAULT_BUILDER_MODEL

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_BUILDER_MODEL", "openai/gpt-4o")
        from src.builder.builder_config import get_builder_model
        assert get_builder_model() == "openai/gpt-4o"

    def test_verbosity_default_high(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_BUILDER_VERBOSITY", raising=False)
        from src.builder.builder_config import get_verbosity
        assert get_verbosity() == "high"

    def test_verbosity_override(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_BUILDER_VERBOSITY", "low")
        from src.builder.builder_config import get_verbosity
        assert get_verbosity() == "low"

    def test_invalid_verbosity_falls_back(self, monkeypatch):
        """잘못된 verbosity 값 → 기본값 high으로 fallback."""
        monkeypatch.setenv("OPENROUTER_BUILDER_VERBOSITY", "extreme")
        from src.builder.builder_config import get_verbosity
        assert get_verbosity() == "high"

    def test_paid_model_reflected_in_payload(self, monkeypatch):
        """유료 모델 설정 시 API payload에 반영."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("OPENROUTER_BUILDER_MODEL", "openai/gpt-4o")
        captured = {}

        def fake_post(url, json, headers, timeout):
            captured["model"] = json.get("model")
            m = MagicMock()
            m.raise_for_status = MagicMock()
            m.json.return_value = {"choices": [{"message": {"content": "1. action one\n2. action two"}}]}
            return m

        import httpx
        monkeypatch.setattr(httpx, "post", fake_post)
        from src.builder.builder_service import run_builder
        run_builder("버그 수정", "code_fix", [])
        assert captured["model"] == "openai/gpt-4o"

    def test_no_api_key_returns_stub(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_BUILDER_MODEL", "openai/gpt-4o")
        from src.builder.builder_service import run_builder
        from src.builder.builder_schema import BUILDER_STATUS_CREATED
        result, model_id = run_builder("버그 수정", "code_fix", [])
        assert result.builder_status == BUILDER_STATUS_CREATED
        assert model_id is None


# ===========================================================================
# reviewer_config 테스트
# ===========================================================================

class TestReviewerConfig:
    def test_default_model(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_REVIEWER_MODEL", raising=False)
        from src.reviewer.reviewer_config import get_reviewer_model, DEFAULT_REVIEWER_MODEL
        assert get_reviewer_model() == DEFAULT_REVIEWER_MODEL

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_REVIEWER_MODEL", "openai/gpt-4o-mini")
        from src.reviewer.reviewer_config import get_reviewer_model
        assert get_reviewer_model() == "openai/gpt-4o-mini"

    def test_default_is_openrouter_auto(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_REVIEWER_MODEL", raising=False)
        from src.reviewer.reviewer_config import DEFAULT_REVIEWER_MODEL
        assert DEFAULT_REVIEWER_MODEL == "openrouter/auto"


# ===========================================================================
# 역할별 모델 독립 분리 테스트
# ===========================================================================

class TestRoleModelIsolation:
    """각 역할의 모델이 서로 독립적으로 설정 가능함을 검증."""

    def test_each_role_uses_own_env(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_PLANNER_MODEL", "anthropic/claude-sonnet-4-5")
        monkeypatch.setenv("OPENROUTER_BUILDER_MODEL", "openai/gpt-4o")
        monkeypatch.setenv("OPENROUTER_REVIEWER_MODEL", "openai/gpt-4o-mini")

        from src.planner.planner_config import get_planner_model
        from src.builder.builder_config import get_builder_model
        from src.reviewer.reviewer_config import get_reviewer_model

        assert get_planner_model() == "anthropic/claude-sonnet-4-5"
        assert get_builder_model() == "openai/gpt-4o"
        assert get_reviewer_model() == "openai/gpt-4o-mini"

    def test_planner_override_does_not_affect_builder(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_PLANNER_MODEL", "anthropic/claude-sonnet-4-5")
        monkeypatch.delenv("OPENROUTER_BUILDER_MODEL", raising=False)

        from src.planner.planner_config import get_planner_model
        from src.builder.builder_config import get_builder_model, DEFAULT_BUILDER_MODEL

        assert get_planner_model() == "anthropic/claude-sonnet-4-5"
        assert get_builder_model() == DEFAULT_BUILDER_MODEL

    def test_all_defaults_are_consistent(self, monkeypatch):
        """모든 역할의 기본값이 openrouter/auto로 통일."""
        for env in ["OPENROUTER_PLANNER_MODEL", "OPENROUTER_BUILDER_MODEL",
                    "OPENROUTER_REVIEWER_MODEL"]:
            monkeypatch.delenv(env, raising=False)

        from src.planner.planner_config import DEFAULT_PLANNER_MODEL
        from src.builder.builder_config import DEFAULT_BUILDER_MODEL
        from src.reviewer.reviewer_config import DEFAULT_REVIEWER_MODEL

        assert DEFAULT_PLANNER_MODEL == "openrouter/auto"
        assert DEFAULT_BUILDER_MODEL == "openrouter/auto"
        assert DEFAULT_REVIEWER_MODEL == "openrouter/auto"
