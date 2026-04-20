"""
LLM Reviewer 모델 설정 — OpenRouter env 기반.

환경변수:
  OPENROUTER_REVIEWER_MODEL   — 기본값: openrouter/auto
  OPENROUTER_API_KEY          — 없으면 stub 모드

기본값 의도:
  openrouter/auto → OpenRouter가 가격/성능 기준으로 자동 선택.
  유료 전환 시: OPENROUTER_REVIEWER_MODEL=anthropic/claude-sonnet-4-5
"""
from __future__ import annotations

import os

DEFAULT_REVIEWER_MODEL = "openrouter/auto"
_ENV_KEY = "OPENROUTER_REVIEWER_MODEL"


def get_reviewer_model() -> str:
    """OPENROUTER_REVIEWER_MODEL env 값 반환. 없으면 DEFAULT_REVIEWER_MODEL."""
    return os.environ.get(_ENV_KEY, DEFAULT_REVIEWER_MODEL)
