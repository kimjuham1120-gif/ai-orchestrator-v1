"""Builder LLM 설정 — 환경변수 v1 기준."""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# 환경변수 키 (v1 SSOT)
# ---------------------------------------------------------------------------
ENV_API_KEY        = "OPENROUTER_API_KEY"
ENV_BASE_URL       = "OPENROUTER_BASE_URL"
ENV_BUILDER_MODEL  = "OPENROUTER_BUILDER_MODEL"
ENV_VERBOSITY      = "OPENROUTER_BUILDER_VERBOSITY"

# ---------------------------------------------------------------------------
# 기본값
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL      = "https://openrouter.ai/api/v1"
DEFAULT_BUILDER_MODEL = "anthropic/claude-3-5-sonnet"
DEFAULT_VERBOSITY     = "high"
CHAT_PATH             = "/chat/completions"


def get_api_key() -> str | None:
    return os.environ.get(ENV_API_KEY) or None


def get_base_url() -> str:
    return os.environ.get(ENV_BASE_URL) or DEFAULT_BASE_URL


def get_builder_model() -> str:
    return os.environ.get(ENV_BUILDER_MODEL) or DEFAULT_BUILDER_MODEL


def get_builder_verbosity() -> str:
    return os.environ.get(ENV_VERBOSITY) or DEFAULT_VERBOSITY


def is_llm_ready() -> bool:
    return get_api_key() is not None
