"""
Builder 모델 설정 — OpenRouter env 기반.

환경변수:
  OPENROUTER_BUILDER_MODEL     — 기본값: openrouter/auto
  OPENROUTER_BUILDER_VERBOSITY — 기본값: high (low/medium/high)
  OPENROUTER_BASE_URL          — 기본값: https://openrouter.ai/api/v1
  OPENROUTER_API_KEY           — 없으면 stub 모드

유료 전환 시:
  OPENROUTER_BUILDER_MODEL=anthropic/claude-sonnet-4-5
  OPENROUTER_BUILDER_VERBOSITY=high
"""
from __future__ import annotations

import os

DEFAULT_BUILDER_MODEL = "openrouter/auto"
DEFAULT_VERBOSITY = "high"

_ENV_MODEL = "OPENROUTER_BUILDER_MODEL"
_ENV_VERBOSITY = "OPENROUTER_BUILDER_VERBOSITY"

# builder_service.py 호환용 — URL은 BASE_URL env에서 읽음
def _get_openrouter_url() -> str:
    base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    return f"{base.rstrip('/')}/chat/completions"

_OPENROUTER_URL = _get_openrouter_url()


def get_builder_model() -> str:
    """OPENROUTER_BUILDER_MODEL env 값 반환. 없으면 DEFAULT_BUILDER_MODEL."""
    return os.environ.get(_ENV_MODEL, DEFAULT_BUILDER_MODEL)


def get_verbosity() -> str:
    """OPENROUTER_BUILDER_VERBOSITY env 값 반환. 없으면 high."""
    v = os.environ.get(_ENV_VERBOSITY, DEFAULT_VERBOSITY).lower()
    if v not in ("low", "medium", "high"):
        return DEFAULT_VERBOSITY
    return v
