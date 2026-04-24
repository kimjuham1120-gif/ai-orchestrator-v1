"""
Day 133 — model_pricing 단위 테스트 (Step 14-1)

테스트 포인트:
  1. 알려진 모델 단가 조회
  2. 알려지지 않은 모델 → 기본값
  3. calculate_cost 정확성
  4. 캐시 히트 할인 반영
  5. 방어적 입력 처리 (음수, None, 문자열)
  6. estimate_cost_from_usage
"""
from __future__ import annotations

import pytest

from src.utils.model_pricing import (
    MODEL_PRICING,
    calculate_cost,
    estimate_cost_from_usage,
    get_pricing,
)


# ===========================================================================
# 1. 단가 조회
# ===========================================================================

class TestGetPricing:
    def test_sonnet_4_6_known(self):
        p = get_pricing("anthropic/claude-sonnet-4-6")
        assert p["input"] == 3.00
        assert p["output"] == 15.00
        assert p["cache_hit"] == 0.30

    def test_opus_4_7_known(self):
        p = get_pricing("anthropic/claude-opus-4-7")
        assert p["input"] == 5.00
        assert p["output"] == 25.00

    def test_haiku_4_5_known(self):
        p = get_pricing("anthropic/claude-haiku-4-5")
        assert p["input"] == 1.00
        assert p["output"] == 5.00

    def test_gpt_5_4_known(self):
        p = get_pricing("openai/gpt-5.4")
        assert p["input"] == 2.50
        assert p["output"] == 15.00

    def test_gemini_3_1_pro_known(self):
        p = get_pricing("google/gemini-3.1-pro-preview")
        assert p["input"] == 1.25
        assert p["output"] == 5.00

    def test_dot_and_dash_variants_equivalent(self):
        """4.6과 4-6 표기 둘 다 인식해야 함."""
        dot = get_pricing("anthropic/claude-sonnet-4.6")
        dash = get_pricing("anthropic/claude-sonnet-4-6")
        assert dot == dash

    def test_unknown_model_returns_default(self):
        p = get_pricing("some/unknown-model")
        assert p["input"] > 0
        assert p["output"] > 0
        assert p["cache_hit"] > 0

    def test_empty_model_returns_default(self):
        p = get_pricing("")
        assert p["input"] > 0

    def test_case_insensitive_match(self):
        p1 = get_pricing("ANTHROPIC/CLAUDE-SONNET-4-6")
        p2 = get_pricing("anthropic/claude-sonnet-4-6")
        assert p1 == p2

    def test_returns_copy_not_reference(self):
        """반환된 dict를 수정해도 원본 테이블이 변하지 않아야."""
        p = get_pricing("anthropic/claude-sonnet-4-6")
        p["input"] = 999.0
        # 재조회 시 원래 값
        assert get_pricing("anthropic/claude-sonnet-4-6")["input"] == 3.00


# ===========================================================================
# 2. calculate_cost — 기본
# ===========================================================================

class TestCalculateCostBasic:
    def test_sonnet_1k_prompt_500_completion(self):
        """1k 입력 + 500 출력 @ Sonnet = (1000×3 + 500×15) / 1M = 0.0105"""
        cost = calculate_cost(
            model="anthropic/claude-sonnet-4-6",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        assert cost == pytest.approx(0.0105, abs=1e-6)

    def test_opus_same_tokens_more_expensive(self):
        """같은 토큰 수에서 Opus가 Sonnet보다 비싸야."""
        opus = calculate_cost("anthropic/claude-opus-4-7", 1000, 500)
        sonnet = calculate_cost("anthropic/claude-sonnet-4-6", 1000, 500)
        assert opus > sonnet

    def test_haiku_cheapest(self):
        haiku = calculate_cost("anthropic/claude-haiku-4-5", 1000, 500)
        sonnet = calculate_cost("anthropic/claude-sonnet-4-6", 1000, 500)
        assert haiku < sonnet

    def test_zero_tokens_zero_cost(self):
        cost = calculate_cost("anthropic/claude-sonnet-4-6", 0, 0)
        assert cost == 0.0

    def test_only_input_tokens(self):
        """출력 0이면 입력 비용만."""
        cost = calculate_cost("anthropic/claude-sonnet-4-6", 1000, 0)
        assert cost == pytest.approx(0.003, abs=1e-6)

    def test_only_output_tokens(self):
        cost = calculate_cost("anthropic/claude-sonnet-4-6", 0, 1000)
        assert cost == pytest.approx(0.015, abs=1e-6)

    def test_large_volume(self):
        """1M 입력 + 1M 출력 @ Sonnet = 3 + 15 = 18 USD"""
        cost = calculate_cost(
            model="anthropic/claude-sonnet-4-6",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
        )
        assert cost == pytest.approx(18.0, abs=1e-4)


# ===========================================================================
# 3. 캐시 히트 할인
# ===========================================================================

class TestCacheHitDiscount:
    def test_cached_cheaper_than_uncached(self):
        uncached = calculate_cost("anthropic/claude-sonnet-4-6", 10000, 0, cached=False)
        cached = calculate_cost("anthropic/claude-sonnet-4-6", 10000, 0, cached=True)
        assert cached < uncached

    def test_cached_input_90_percent_discount_anthropic(self):
        """Anthropic 캐시 히트 = 입력 단가의 10% (90% 할인)"""
        pricing = get_pricing("anthropic/claude-sonnet-4-6")
        assert pricing["cache_hit"] == pytest.approx(pricing["input"] * 0.10)

    def test_cached_does_not_affect_output(self):
        """출력 토큰 비용은 캐싱 여부 무관."""
        cost_no_input_uncached = calculate_cost(
            "anthropic/claude-sonnet-4-6", 0, 500, cached=False
        )
        cost_no_input_cached = calculate_cost(
            "anthropic/claude-sonnet-4-6", 0, 500, cached=True
        )
        assert cost_no_input_uncached == cost_no_input_cached


# ===========================================================================
# 4. 방어적 입력
# ===========================================================================

class TestDefensiveInputs:
    def test_negative_prompt_tokens_clamped(self):
        cost = calculate_cost("anthropic/claude-sonnet-4-6", -100, 500)
        # 음수는 0으로 취급 → 출력만 계산
        assert cost == pytest.approx(0.0075, abs=1e-6)

    def test_negative_completion_tokens_clamped(self):
        cost = calculate_cost("anthropic/claude-sonnet-4-6", 1000, -100)
        assert cost == pytest.approx(0.003, abs=1e-6)

    def test_none_tokens_treated_as_zero(self):
        cost = calculate_cost("anthropic/claude-sonnet-4-6", None, None)
        assert cost == 0.0

    def test_unknown_model_still_calculates(self):
        """미등록 모델이어도 기본값으로 계산 가능."""
        cost = calculate_cost("weird/unknown-model-xyz", 1000, 500)
        assert cost > 0

    def test_float_tokens_coerced(self):
        """float 입력도 int로 변환되어야."""
        cost = calculate_cost("anthropic/claude-sonnet-4-6", 1000.9, 500.5)
        # int(1000.9) = 1000, int(500.5) = 500
        assert cost == pytest.approx(0.0105, abs=1e-6)


# ===========================================================================
# 5. estimate_cost_from_usage
# ===========================================================================

class TestEstimateFromUsage:
    def test_valid_usage_dict(self):
        usage = {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
        }
        cost = estimate_cost_from_usage("anthropic/claude-sonnet-4-6", usage)
        assert cost == pytest.approx(0.0105, abs=1e-6)

    def test_none_usage_returns_zero(self):
        cost = estimate_cost_from_usage("anthropic/claude-sonnet-4-6", None)
        assert cost == 0.0

    def test_empty_usage_returns_zero(self):
        cost = estimate_cost_from_usage("anthropic/claude-sonnet-4-6", {})
        assert cost == 0.0

    def test_partial_usage_missing_completion(self):
        usage = {"prompt_tokens": 1000}
        cost = estimate_cost_from_usage("anthropic/claude-sonnet-4-6", usage)
        # 입력만 → 0.003
        assert cost == pytest.approx(0.003, abs=1e-6)

    def test_non_dict_usage_returns_zero(self):
        cost = estimate_cost_from_usage("anthropic/claude-sonnet-4-6", "not a dict")
        assert cost == 0.0

    def test_cached_flag_passed_through(self):
        usage = {"prompt_tokens": 10000, "completion_tokens": 0}
        cached = estimate_cost_from_usage(
            "anthropic/claude-sonnet-4-6", usage, cached=True
        )
        uncached = estimate_cost_from_usage(
            "anthropic/claude-sonnet-4-6", usage, cached=False
        )
        assert cached < uncached


# ===========================================================================
# 6. MODEL_PRICING 테이블 무결성
# ===========================================================================

class TestPricingTableIntegrity:
    def test_all_entries_have_required_keys(self):
        for model, pricing in MODEL_PRICING.items():
            assert "input" in pricing, f"{model}: 'input' 누락"
            assert "output" in pricing, f"{model}: 'output' 누락"
            assert "cache_hit" in pricing, f"{model}: 'cache_hit' 누락"

    def test_all_prices_positive(self):
        for model, pricing in MODEL_PRICING.items():
            assert pricing["input"] > 0, f"{model}: 입력 단가 음수"
            assert pricing["output"] > 0, f"{model}: 출력 단가 음수"
            assert pricing["cache_hit"] > 0, f"{model}: 캐시 단가 음수"

    def test_cache_hit_cheaper_than_input(self):
        """캐시 히트는 항상 일반 입력보다 저렴해야."""
        for model, pricing in MODEL_PRICING.items():
            assert pricing["cache_hit"] <= pricing["input"], \
                f"{model}: 캐시 히트가 일반 입력보다 비쌈"

    def test_output_more_expensive_than_input(self):
        """일반적으로 출력이 입력보다 비쌈 (Claude·GPT 모두)."""
        # OpenRouter auto는 제외 (Sonnet 기준)
        for model, pricing in MODEL_PRICING.items():
            assert pricing["output"] >= pricing["input"], \
                f"{model}: 출력이 입력보다 저렴 (이상함)"
