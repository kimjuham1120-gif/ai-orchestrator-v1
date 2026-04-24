"""
src/utils/llm_utils.py — LLM 공통 유틸리티 (Day 123, Step 13 + Day 131, Step 14-2)

기능:
  1. 프롬프트 캐싱 — OpenRouter cache_control 헤더 (Claude 90%, GPT 50% 할인)
  2. Exponential backoff 재시도 — 최대 2회, 1s/2s 대기
  3. 공통 _call_llm() 헬퍼 — 모든 Phase에서 재사용
  4. (Day 131) call_llm_json — JSON 응답 파싱 실패 시 보정 프롬프트로 재시도

사용법:
  from src.utils.llm_utils import call_llm, call_llm_json

  # 기본 호출 (캐싱 + 재시도 자동 적용)
  text = call_llm(prompt, model, timeout)

  # JSON 응답을 파싱까지 보장하는 호출
  data = call_llm_json(prompt, model, timeout)  # dict 또는 None

  # 캐싱 비활성화
  text = call_llm(prompt, model, timeout, use_cache=False)

캐싱 정책:
  PROMPT_CACHE_ENABLED=true (기본값) 로 전역 on/off
  프롬프트 길이 >= 1024 토큰 추정 시에만 cache_control 추가
  (짧은 프롬프트는 캐싱 오버헤드가 이득보다 큼)
"""
from __future__ import annotations

import json
import os
import time
import re
from typing import Any, Optional

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


# ---------------------------------------------------------------------------
# JSON 응답 전용 헬퍼 (Day 131, Step 14-2)
# ---------------------------------------------------------------------------

def _strip_json_fence(text: str) -> str:
    """
    LLM JSON 응답에서 흔히 나오는 오염 제거.

    처리 대상:
      - ```json ... ``` 코드 블록 래퍼
      - ``` ... ``` 언어 명시 없는 래퍼
      - 앞뒤 공백·개행
      - 앞쪽 설명문 (첫 '{' 또는 '[' 이전 모두 제거)
      - 뒤쪽 설명문 (마지막 '}' 또는 ']' 이후 모두 제거)

    JSON 파싱 전 전처리용. 파싱 자체는 호출자가 수행.
    """
    if not text:
        return ""

    cleaned = text.strip()

    # 1. 코드 블록 래퍼 제거 (markdown, md, json 래벨 포함)
    cleaned = re.sub(r"^```(?:json|md|markdown)?\s*\n", "", cleaned)
    cleaned = re.sub(r"\n```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    # 2. 첫 JSON 시작 문자 찾기 ('{' 또는 '[')
    start_brace = cleaned.find("{")
    start_bracket = cleaned.find("[")
    starts = [s for s in (start_brace, start_bracket) if s >= 0]
    if not starts:
        return cleaned  # JSON이 아닐 가능성, 원본 반환
    start = min(starts)

    # 3. 마지막 JSON 종료 문자 찾기 ('}' 또는 ']')
    end_brace = cleaned.rfind("}")
    end_bracket = cleaned.rfind("]")
    end = max(end_brace, end_bracket)
    if end < start:
        return cleaned  # 비정상, 원본 반환

    return cleaned[start:end + 1].strip()


def call_llm_json(
    prompt: str,
    model: str,
    timeout: float,
    retry_limit: int = 2,
    use_cache: bool = True,
) -> Optional[Any]:
    """
    JSON 응답을 보장하는 LLM 호출.

    파싱 실패 시 보정 프롬프트로 최대 retry_limit 회 재시도.
    네트워크 재시도는 내부 call_llm이 이미 처리.

    Args:
      prompt: 원본 프롬프트 (JSON만 출력하도록 지시해야 함)
      model: OpenRouter 모델 ID
      timeout: 각 호출의 타임아웃 (초)
      retry_limit: JSON 파싱 실패 시 추가 재시도 횟수 (기본 2)
                   총 시도 = retry_limit + 1
      use_cache: 프롬프트 캐싱 여부

    Returns:
      파싱된 dict 또는 list. 최종 실패 시 None.

    실패 조건:
      - API 키 없음 → 첫 call_llm에서 None → 즉시 None 반환
      - 모든 재시도 JSON 파싱 실패 → None
      - LLM 응답 자체가 None (빈 응답, 네트워크 완전 실패) → None

    사용 예:
      data = call_llm_json(
          "다음 카페 특성을 JSON으로 분류: ...",
          "anthropic/claude-haiku-4-5",
          timeout=30.0,
      )
      if data is None:
          # fallback 처리
          ...
    """
    if retry_limit < 0:
        retry_limit = 0

    current_prompt = prompt
    last_error: Optional[str] = None

    for attempt in range(retry_limit + 1):
        text = call_llm(current_prompt, model, timeout, use_cache=use_cache)

        # LLM 호출 자체 실패 (네트워크, API 키 없음 등)
        if text is None:
            return None

        # 빈 응답
        stripped = text.strip()
        if not stripped:
            last_error = "빈 응답"
        else:
            # JSON 추출 시도
            candidate = _strip_json_fence(stripped)
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"

        # 마지막 시도면 종료
        if attempt >= retry_limit:
            break

        # 보정 프롬프트 작성 후 재시도
        current_prompt = (
            f"{prompt}\n\n"
            f"[이전 응답이 JSON 파싱에 실패했습니다: {last_error}]\n"
            f"다음 요구사항을 반드시 지키세요:\n"
            f"- 유효한 JSON만 출력 (객체 또는 배열)\n"
            f"- 코드 블록 래퍼(```) 사용 금지\n"
            f"- 앞뒤 설명문·인사말 금지\n"
            f"- 한글 포함 가능, 단 문자열은 큰따옴표로 감쌀 것\n"
        )

    # 모든 재시도 소진
    return None
