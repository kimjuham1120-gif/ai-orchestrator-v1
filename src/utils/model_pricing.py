"""
src/utils/model_pricing.py — 모델별 토큰 단가 + 비용 계산 (Step 14-1)

역할:
  - OpenRouter 통해 호출하는 주요 모델의 per-million-token 단가 보관
  - 토큰 수 → USD 비용 계산 헬퍼
  - Anthropic 프롬프트 캐싱 할인 반영 (입력 캐시 히트 시 90% 할인)

가격 기준:
  - Anthropic 공식 (2026-04 기준)
  - OpenAI 공식 (2026-04 기준)
  - Google Gemini는 추정값 (실측 후 조정 필요)

환경변수:
  없음 (순수 상수 테이블)

사용법:
  from src.utils.model_pricing import calculate_cost, get_pricing

  cost = calculate_cost(
      model="anthropic/claude-sonnet-4-6",
      prompt_tokens=1000,
      completion_tokens=500,
      cached=False,  # 캐시 히트 여부
  )
  # → 약 0.0105 USD
"""
from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# 단가 테이블 (USD per 1M tokens)
# ---------------------------------------------------------------------------
#
# 형식: {"input": 입력 단가, "output": 출력 단가, "cache_hit": 캐시 히트 입력 단가}
# cache_hit이 None이면 입력 단가의 10% (Anthropic 기본 할인)로 계산
#
MODEL_PRICING: dict[str, dict[str, float]] = {
    # --- Anthropic (공식 2026-04) ---
    "anthropic/claude-opus-4-7":          {"input": 5.00,  "output": 25.00, "cache_hit": 0.50},
    "anthropic/claude-opus-4.7":          {"input": 5.00,  "output": 25.00, "cache_hit": 0.50},
    "anthropic/claude-opus-4-6":          {"input": 5.00,  "output": 25.00, "cache_hit": 0.50},
    "anthropic/claude-opus-4.6":          {"input": 5.00,  "output": 25.00, "cache_hit": 0.50},
    "anthropic/claude-sonnet-4-6":        {"input": 3.00,  "output": 15.00, "cache_hit": 0.30},
    "anthropic/claude-sonnet-4.6":        {"input": 3.00,  "output": 15.00, "cache_hit": 0.30},
    "anthropic/claude-haiku-4-5":         {"input": 1.00,  "output":  5.00, "cache_hit": 0.10},
    "anthropic/claude-haiku-4.5":         {"input": 1.00,  "output":  5.00, "cache_hit": 0.10},

    # --- OpenAI (공식 2026-04) ---
    "openai/gpt-5.4":                     {"input": 2.50,  "output": 15.00, "cache_hit": 1.25},
    "openai/gpt-5.4-mini":                {"input": 0.50,  "output":  3.00, "cache_hit": 0.25},
    # Legacy
    "openai/gpt-4o":                      {"input": 2.50,  "output": 10.00, "cache_hit": 1.25},
    "openai/gpt-4o-mini":                 {"input": 0.15,  "output":  0.60, "cache_hit": 0.075},

    # --- Google Gemini (추정값 — 실측 후 조정) ---
    "google/gemini-3.1-pro-preview":      {"input": 1.25,  "output":  5.00, "cache_hit": 0.3125},
    "google/gemini-3.1-pro":              {"input": 1.25,  "output":  5.00, "cache_hit": 0.3125},
    "google/gemini-3.1-flash":            {"input": 0.15,  "output":  0.60, "cache_hit": 0.0375},

    # --- OpenRouter 특수 ---
    "openrouter/auto":                    {"input": 3.00,  "output": 15.00, "cache_hit": 0.30},
    # (실제 라우팅되는 모델에 따라 다르지만, 보수적으로 Sonnet 기준)
}


# 알려지지 않은 모델의 기본 단가 (보수적: Sonnet 4.6 수준)
_DEFAULT_PRICING = {"input": 3.00, "output": 15.00, "cache_hit": 0.30}


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def get_pricing(model: str) -> dict[str, float]:
    """
    모델의 단가 dict 반환. 미등록 모델은 기본값 (Sonnet 수준).

    Returns:
      {"input": float, "output": float, "cache_hit": float}
      단위는 모두 USD per 1M tokens.
    """
    if not model:
        return dict(_DEFAULT_PRICING)

    # 정확한 매칭 우선
    if model in MODEL_PRICING:
        return dict(MODEL_PRICING[model])

    # 대소문자 다르거나 공백 있을 수 있어서 정규화 재시도
    normalized = model.strip().lower()
    for key, value in MODEL_PRICING.items():
        if key.lower() == normalized:
            return dict(value)

    # 못 찾으면 기본값
    return dict(_DEFAULT_PRICING)


def calculate_cost(
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cached: bool = False,
) -> float:
    """
    LLM 호출 비용 계산 (USD).

    Args:
      model: OpenRouter 모델 ID
      prompt_tokens: 입력 토큰 수
      completion_tokens: 출력 토큰 수
      cached: 프롬프트 캐싱 히트 여부 (True면 입력 단가 할인 적용)

    Returns:
      총 비용 (USD, 소수점 6자리 반올림)

    방어적 처리:
      - 음수 토큰 → 0으로 clamp
      - None 토큰 → 0으로 clamp
      - 알 수 없는 모델 → 기본 단가 (Sonnet 수준)
    """
    # 입력 정규화
    p_tok = max(0, int(prompt_tokens or 0))
    c_tok = max(0, int(completion_tokens or 0))

    pricing = get_pricing(model)

    # 입력 단가: 캐시 히트 여부에 따라 선택
    input_rate = pricing["cache_hit"] if cached else pricing["input"]
    output_rate = pricing["output"]

    # per 1M tokens → per token
    cost = (p_tok * input_rate + c_tok * output_rate) / 1_000_000.0

    return round(cost, 6)


def estimate_cost_from_usage(
    model: str,
    usage: Optional[dict],
    cached: bool = False,
) -> float:
    """
    OpenRouter usage 딕셔너리에서 비용 계산.

    OpenRouter usage 형식 예시:
      {
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "total_tokens": 1500,
      }

    Args:
      model: 모델 ID
      usage: OpenRouter 응답의 usage dict (None 허용)
      cached: 캐시 히트 여부

    Returns:
      비용 (USD). usage None이면 0.0 반환.
    """
    if not usage or not isinstance(usage, dict):
        return 0.0

    return calculate_cost(
        model=model,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        cached=cached,
    )
