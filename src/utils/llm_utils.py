"""
src/utils/llm_utils.py — LLM 공통 유틸리티.

기능:
  1. 프롬프트 캐싱 — OpenRouter cache_control (Claude 90%, GPT 50% 할인)
  2. Exponential backoff 재시도 — 최대 2회, 1s/2s 대기
  3. JSON 응답 전용 래퍼 — call_llm_json (Day 131, Step 14-2)
  4. 자동 비용/토큰 로깅 — set_llm_context (Day 136, Step 14-1 단계 3)

사용법:
  # 기본 호출 (로깅 안 됨)
  from src.utils.llm_utils import call_llm
  text = call_llm(prompt, model, timeout)

  # 자동 로깅 (컨텍스트 설정 후)
  from src.utils.llm_utils import set_llm_context, call_llm
  set_llm_context(
      db_path="orchestrator.db",
      project_id="proj-1",
      run_id="run-1",
      phase="0.5",
  )
  text = call_llm(prompt, model, timeout)
  # ↑ 자동으로 llm_calls 테이블에 INSERT

  # 컨텍스트 해제
  clear_llm_context()

자동 로깅 동작:
  - 컨텍스트 설정 시에만 작동
  - 실패해도 예외 전파 없음 (로깅 실패가 본 작업 방해 X)
  - httpx 응답의 usage 필드에서 토큰 추출
  - model_pricing으로 비용 계산
  - cached 여부는 프롬프트 길이 기준 추정

캐싱 정책:
  PROMPT_CACHE_ENABLED=true (기본값) 로 전역 on/off
  프롬프트 >= 4000자일 때만 cache_control 추가
"""
from __future__ import annotations

import contextvars
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

_CACHE_ENABLED_DEFAULT = True
_CACHE_MIN_CHARS = 4000      # 약 1000 토큰 이상일 때만 캐싱
_MAX_RETRIES = 2
_RETRY_DELAYS = [1.0, 2.0]   # exponential backoff


def _is_cache_enabled() -> bool:
    val = os.environ.get("PROMPT_CACHE_ENABLED", "true").strip().lower()
    return val != "false"


# ---------------------------------------------------------------------------
# 자동 로깅 컨텍스트 (Day 136, Step 14-1 단계 3)
# ---------------------------------------------------------------------------

@dataclass
class LLMContext:
    """
    현재 실행 중인 Phase의 컨텍스트.
    call_llm이 자동 로깅할 때 이 정보를 사용.
    """
    db_path: str
    project_id: Optional[str] = None
    run_id: Optional[str] = None
    phase: Optional[str] = None


# 모듈 레벨 컨텍스트 변수 (async 안전)
_current_context: contextvars.ContextVar[Optional[LLMContext]] = contextvars.ContextVar(
    "_llm_context", default=None
)


def set_llm_context(
    db_path: str,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    phase: Optional[str] = None,
) -> None:
    """
    현재 실행 컨텍스트 설정. 이후 call_llm 호출이 자동 로깅됨.

    Args:
      db_path: SQLite DB 경로 (필수)
      project_id: 프로젝트 ID (예산 집계용)
      run_id: run ID (Phase 호출 이력용)
      phase: "0.5" / "1" / "3a" / "3b" / "4-structure" 등

    Note:
      빈 db_path를 주면 컨텍스트 해제 효과.
    """
    if not db_path:
        clear_llm_context()
        return

    ctx = LLMContext(
        db_path=db_path,
        project_id=project_id,
        run_id=run_id,
        phase=phase,
    )
    _current_context.set(ctx)


def clear_llm_context() -> None:
    """로깅 컨텍스트 해제."""
    _current_context.set(None)


def get_llm_context() -> Optional[LLMContext]:
    """현재 컨텍스트 조회 (디버깅용)."""
    return _current_context.get()


# ---------------------------------------------------------------------------
# 프롬프트 → 캐싱 가능한 메시지 구조 변환
# ---------------------------------------------------------------------------

def _build_messages(prompt: str, use_cache: bool) -> list:
    """
    프롬프트를 OpenRouter 메시지 형식으로 변환.
    캐싱 활성화 시 긴 프롬프트에 cache_control 추가.
    """
    if use_cache and _is_cache_enabled() and len(prompt) >= _CACHE_MIN_CHARS:
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
    return [{"role": "user", "content": prompt}]


def _cache_applied(prompt: str, use_cache: bool) -> bool:
    """프롬프트에 cache_control이 적용되었는지 판정 (로깅용)."""
    return use_cache and _is_cache_enabled() and len(prompt) >= _CACHE_MIN_CHARS


# ---------------------------------------------------------------------------
# 마크다운 wrapper 제거
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
# 자동 로깅 헬퍼 (내부 전용)
# ---------------------------------------------------------------------------

def _try_log_call(
    model: str,
    response_json: Optional[dict],
    cached: bool,
    duration_ms: int,
    status: str,
    error: Optional[str] = None,
) -> None:
    """
    컨텍스트 있으면 llm_calls 테이블에 기록. 실패해도 예외 전파 없음.

    - 순환 import 방지: artifact_store와 model_pricing을 지연 import.
    - 테스트 환경에서는 이 함수가 아무것도 안 함 (컨텍스트 없음).
    """
    ctx = _current_context.get()
    if ctx is None:
        return

    try:
        # 지연 import (순환 참조 방지, 로딩 비용 분산)
        from src.store.artifact_store import log_llm_call
        from src.utils.model_pricing import estimate_cost_from_usage

        usage = {}
        if isinstance(response_json, dict):
            u = response_json.get("usage")
            if isinstance(u, dict):
                usage = u

        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        cost = estimate_cost_from_usage(model, usage, cached=cached)

        log_llm_call(
            db_path=ctx.db_path,
            project_id=ctx.project_id,
            run_id=ctx.run_id,
            phase=ctx.phase,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            cached=cached,
            duration_ms=duration_ms,
            status=status,
            error=error,
        )
    except Exception:
        # 로깅 자체가 실패해도 본 흐름 방해 금지
        pass


# ---------------------------------------------------------------------------
# 핵심 공개 API — call_llm
# ---------------------------------------------------------------------------

def call_llm(
    prompt: str,
    model: str,
    timeout: float,
    use_cache: bool = True,
) -> Optional[str]:
    """
    OpenRouter LLM 호출 — 캐싱 + 재시도 + 자동 로깅.

    Args:
      prompt: 사용자 프롬프트
      model: OpenRouter 모델 ID
      timeout: 요청 타임아웃 (초)
      use_cache: 캐싱 활성화 여부

    Returns:
      응답 텍스트 (마크다운 wrapper 제거됨). 실패 시 None.

    자동 로깅:
      set_llm_context()로 컨텍스트 설정된 경우에만 llm_calls 테이블에 INSERT.
      로깅 실패해도 본 호출엔 영향 없음.

    재시도 정책:
      - 네트워크 오류 / 5xx → 최대 2회 재시도
      - 4xx → 재시도 없음
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None

    messages = _build_messages(prompt, use_cache)
    cached = _cache_applied(prompt, use_cache)
    start_time = time.time()

    last_response_json: Optional[dict] = None
    last_error: Optional[str] = None

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

            # 4xx → 재시도 없이 실패
            if 400 <= response.status_code < 500:
                duration_ms = int((time.time() - start_time) * 1000)
                _try_log_call(
                    model=model,
                    response_json=None,
                    cached=cached,
                    duration_ms=duration_ms,
                    status="failed",
                    error=f"HTTP {response.status_code}",
                )
                return None

            response.raise_for_status()
            last_response_json = response.json()
            content = last_response_json["choices"][0]["message"]["content"]

            # 성공 로깅
            duration_ms = int((time.time() - start_time) * 1000)
            _try_log_call(
                model=model,
                response_json=last_response_json,
                cached=cached,
                duration_ms=duration_ms,
                status="success",
            )

            return clean_markdown_wrapper(content) if content else None

        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[attempt]
                time.sleep(delay)
            continue

    # 모든 재시도 소진
    duration_ms = int((time.time() - start_time) * 1000)
    _try_log_call(
        model=model,
        response_json=None,
        cached=cached,
        duration_ms=duration_ms,
        status="failed",
        error=last_error,
    )
    return None


# ---------------------------------------------------------------------------
# JSON 응답 전용 헬퍼 (Day 131, Step 14-2)
# ---------------------------------------------------------------------------

def _strip_json_fence(text: str) -> str:
    """LLM JSON 응답에서 흔히 나오는 오염 제거."""
    if not text:
        return ""

    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json|md|markdown)?\s*\n", "", cleaned)
    cleaned = re.sub(r"\n```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    start_brace = cleaned.find("{")
    start_bracket = cleaned.find("[")
    starts = [s for s in (start_brace, start_bracket) if s >= 0]
    if not starts:
        return cleaned
    start = min(starts)

    end_brace = cleaned.rfind("}")
    end_bracket = cleaned.rfind("]")
    end = max(end_brace, end_bracket)
    if end < start:
        return cleaned

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
    """
    if retry_limit < 0:
        retry_limit = 0

    current_prompt = prompt
    last_error: Optional[str] = None

    for attempt in range(retry_limit + 1):
        text = call_llm(current_prompt, model, timeout, use_cache=use_cache)

        if text is None:
            return None

        stripped = text.strip()
        if not stripped:
            last_error = "빈 응답"
        else:
            candidate = _strip_json_fence(stripped)
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"

        if attempt >= retry_limit:
            break

        current_prompt = (
            f"{prompt}\n\n"
            f"[이전 응답이 JSON 파싱에 실패했습니다: {last_error}]\n"
            f"다음 요구사항을 반드시 지키세요:\n"
            f"- 유효한 JSON만 출력 (객체 또는 배열)\n"
            f"- 코드 블록 래퍼(```) 사용 금지\n"
            f"- 앞뒤 설명문·인사말 금지\n"
            f"- 한글 포함 가능, 단 문자열은 큰따옴표로 감쌀 것\n"
        )

    return None
