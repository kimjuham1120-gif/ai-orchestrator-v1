"""Planner LLM 설정 — 환경변수 v1 기준."""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# 환경변수 키 (v1 SSOT)
# ---------------------------------------------------------------------------
ENV_API_KEY          = "OPENROUTER_API_KEY"
ENV_BASE_URL         = "OPENROUTER_BASE_URL"
ENV_PLANNER_MODEL    = "OPENROUTER_PLANNER_MODEL"
ENV_REASONING_EFFORT = "OPENROUTER_PLANNER_REASONING_EFFORT"

# ---------------------------------------------------------------------------
# 기본값
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL         = "https://openrouter.ai/api/v1"
DEFAULT_PLANNER_MODEL    = "openai/gpt-4o"
DEFAULT_REASONING_EFFORT = "medium"
CHAT_PATH                = "/chat/completions"


def get_api_key() -> str | None:
    return os.environ.get(ENV_API_KEY) or None


def get_base_url() -> str:
    return os.environ.get(ENV_BASE_URL) or DEFAULT_BASE_URL


def get_planner_model() -> str:
    return os.environ.get(ENV_PLANNER_MODEL) or DEFAULT_PLANNER_MODEL


def get_planner_reasoning_effort() -> str:
    return os.environ.get(ENV_REASONING_EFFORT) or DEFAULT_REASONING_EFFORT


def is_llm_ready() -> bool:
    return get_api_key() is not None
