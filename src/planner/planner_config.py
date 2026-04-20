"""
Planner 모델 설정 — OpenRouter env 기반.

환경변수:
  OPENROUTER_PLANNER_MODEL            — 기본값: openrouter/auto
  OPENROUTER_PLANNER_REASONING_EFFORT — 기본값: medium (low/medium/high)
  OPENROUTER_BASE_URL                 — 기본값: https://openrouter.ai/api/v1
  OPENROUTER_API_KEY                  — 없으면 stub 모드

유료 전환 시:
  OPENROUTER_PLANNER_MODEL=anthropic/claude-sonnet-4-5
  OPENROUTER_PLANNER_REASONING_EFFORT=high
"""
from __future__ import annotations

import os

DEFAULT_PLANNER_MODEL = "openrouter/auto"
DEFAULT_REASONING_EFFORT = "medium"

_ENV_MODEL = "OPENROUTER_PLANNER_MODEL"
_ENV_EFFORT = "OPENROUTER_PLANNER_REASONING_EFFORT"

# planner_service.py 호환용 — URL은 BASE_URL env에서 읽음
def _get_openrouter_url() -> str:
    base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    return f"{base.rstrip('/')}/chat/completions"

_OPENROUTER_URL = _get_openrouter_url()


def get_planner_model() -> str:
    """OPENROUTER_PLANNER_MODEL env 값 반환. 없으면 DEFAULT_PLANNER_MODEL."""
    return os.environ.get(_ENV_MODEL, DEFAULT_PLANNER_MODEL)


def get_reasoning_effort() -> str:
    """OPENROUTER_PLANNER_REASONING_EFFORT env 값 반환. 없으면 medium."""
    effort = os.environ.get(_ENV_EFFORT, DEFAULT_REASONING_EFFORT).lower()
    if effort not in ("low", "medium", "high"):
        return DEFAULT_REASONING_EFFORT
    return effort
