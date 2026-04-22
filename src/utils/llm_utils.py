"""
src/utils/llm_utils.py — LLM 공통 유틸리티 (Day 123, Step 13)

기능:
  1. 프롬프트 캐싱 — OpenRouter cache_control 헤더 (Claude 90%, GPT 50% 할인)
  2. Exponential backoff 재시도 — 최대 2회, 1s/2s 대기
  3. 공통 _call_llm() 헬퍼 — 모든 Phase에서 재사용

사용법:
  from src.utils.llm_utils import call_llm

  # 기본 호출 (캐싱 + 재시도 자동 적용)
  text = call_llm(prompt, model, timeout)

  # 캐싱 비활성화
  text = call_llm(prompt, model, timeout, use_cache=False)

캐싱 정책:
  PROMPT_CACHE_ENABLED=true (기본값) 로 전역 on/off
  프롬프트 길이 >= 1024 토큰 추정 시에만 cache_control 추가
  (짧은 프롬프트는 캐싱 오버헤드가 이득보다 큼)
"""
from __future__ import annotations

import os
import time
import re
from typing import Optional

import httpx


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

_CACHE_ENABLED_DEFAULT = True
_CACHE_MIN_CHARS = 4000      # 약 1000 토큰 이상일 때만 캐싱 (4자 ≈ 1토큰)
_MAX_RETRIES = 2
_RETRY_DELAYS = [1.0, 2.0]   # 초 단위 (exponential backoff)


def _is_cache_enabled() -> bool:
    val = os.environ.get("PROMPT_CACHE_ENABLED", "true").strip().lower()
    return val != "false"


# ---------------------------------------------------------------------------
# 프롬프트 → 캐싱 가능한 메시지 구조 변환
# ---------------------------------------------------------------------------

def _build_messages(prompt: str, use_cache: bool) -> list:
    """
    프롬프트를 OpenRouter 메시지 형식으로 변환.
    캐싱 활성화 시 긴 프롬프트에 cache_control 추가.
    """
    if use_cache and _is_cache_enabled() and len(prompt) >= _CACHE_MIN_CHARS:
        # cache_control 블록 형식 (OpenRouter / Anthropic 호환)
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ]
    # 기본 형식
    return [{"role": "user", "content": prompt}]


# ---------------------------------------------------------------------------
# 마크다운 wrapper 제거 (기존 모든 Phase에서 반복 사용)
# ---------------------------------------------------------------------------

def clean_markdown_wrapper(text: str) -> str:
    """LLM이 감싼 ```markdown...``` 제거."""
    if not text:
        return text
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:markdown|md|json)?\s*\n", "", cleaned)
    cleaned = re.sub(r"\n```\s*$", "", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# 핵심 공개 API — call_llm (캐싱 + 재시도)
# ---------------------------------------------------------------------------

def call_llm(
    prompt: str,
    model: str,
    timeout: float,
    use_cache: bool = True,
) -> Optional[str]:
    """
    OpenRouter LLM 호출 — 캐싱 + exponential backoff 재시도.

    Args:
      prompt: 사용자 프롬프트 (단일 문자열)
      model: OpenRouter 모델 ID (예: "anthropic/claude-sonnet-4-6")
      timeout: 요청 타임아웃 (초)
      use_cache: 캐싱 활성화 여부 (기본 True)
                 프롬프트가 짧으면 자동으로 캐싱 건너뜀

    Returns:
      응답 텍스트 (마크다운 wrapper 제거됨)
      실패 시 None (예외 전파 없음)

    재시도 정책:
      - 네트워크 오류 / 5xx → 최대 2회 재시도
      - 4xx (잘못된 요청) → 재시도 없음
      - 타임아웃 → 재시도 없음 (이미 느린 상황)
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None

    messages = _build_messages(prompt, use_cache)
    last_error: Optional[Exception] = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                },
                timeout=timeout,
            )

            # 4xx → 재시도 의미 없음 (요청 자체가 잘못됨)
            if 400 <= response.status_code < 500:
                return None

            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return clean_markdown_wrapper(content) if content else None

        except Exception as exc:
            last_error = exc
            # 마지막 시도가 아니면 대기 후 재시도
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[attempt]
                time.sleep(delay)
            continue

    # 모든 재시도 소진
    return None
