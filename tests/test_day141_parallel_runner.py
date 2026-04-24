"""
Day 141 — 병렬 Research Runner 테스트

검증:
  A. 기본 병렬 실행 — 성공 결과 집계
  B. 실패 tolerance — 일부 실패해도 나머지 수집
  C. 전부 실패 / 전부 스킵
  D. 빈 어댑터 리스트
  E. 타임아웃
  F. 비용 집계
  G. ParallelResult 필드 / to_dict
  H. build_default_adapters
  I. 예외 안전성 (_safe_research)
"""
from __future__ import annotations

import time
import pytest
from unittest.mock import MagicMock, patch

from src.research_v2.parallel_runner import (
    run_parallel_research,
    ParallelResult,
    build_default_adapters,
    _safe_research,
    _resolve_overall_timeout,
)
from src.research_v2.base import (
    ResearchAdapter,
    ResearchResult,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_SKIPPED,
)


# ===========================================================================
# 테스트용 페이크 어댑터
# ===========================================================================

class FakeAdapter(ResearchAdapter):
    """완전히 제어 가능한 가짜 어댑터."""

    def __init__(
        self,
        name: str = "fake",
        status: str = STATUS_SUCCESS,
        report: str = "fake report",
        cost: float = 0.01,
        delay_sec: float = 0.0,
        raise_exc: Exception = None,
        model: str = "fake-model",
        timeout: float = 60.0,
    ):
        # ResearchAdapter는 인스턴스 속성으로 덮어쓸 수 있음 (name이 클래스 속성)
        self.name = name
        self._status = status
        self._report = report
        self._cost = cost
        self._delay_sec = delay_sec
        self._raise_exc = raise_exc
        self._model = model
        self._timeout = timeout

    @property
    def default_timeout(self) -> float:
        return self._timeout

    def is_available(self) -> bool:
        # skipped 상태를 테스트하려면 status 체크
        return self._status != STATUS_SKIPPED

    def _do_research(self, query: str, timeout: float) -> ResearchResult:
        if self._delay_sec > 0:
            time.sleep(self._delay_sec)
        if self._raise_exc:
            raise self._raise_exc

        return ResearchResult(
            adapter_name=self.name,
            status=self._status,
            report=self._report if self._status == STATUS_SUCCESS else "",
            model=self._model,
            cost_usd=self._cost,
            error="forced fail" if self._status == STATUS_FAILED else None,
        )


# ===========================================================================
# A. 기본 병렬 실행
# ===========================================================================

class TestBasicParallelExecution:
    def test_single_adapter_success(self):
        adapters = [FakeAdapter("a1", status=STATUS_SUCCESS, cost=0.05)]
        result = run_parallel_research(adapters, "q")

        assert isinstance(result, ParallelResult)
        assert result.query == "q"
        assert len(result.results) == 1
        assert result.success_count == 1
        assert result.has_success is True
        assert result.all_failed is False
        assert result.total_cost_usd == 0.05

    def test_multiple_adapters_all_success(self):
        adapters = [
            FakeAdapter("a1", cost=0.01),
            FakeAdapter("a2", cost=0.02),
            FakeAdapter("a3", cost=0.03),
        ]
        result = run_parallel_research(adapters, "커피 로스팅")

        assert result.success_count == 3
        assert result.failed_count == 0
        assert result.skipped_count == 0
        assert result.total_cost_usd == pytest.approx(0.06, abs=1e-6)
        assert all(r.status == STATUS_SUCCESS for r in result.results)

    def test_duration_measured(self):
        adapters = [FakeAdapter("a1")]
        result = run_parallel_research(adapters, "q")
        assert result.total_duration_ms >= 0


# ===========================================================================
# B. 실패 tolerance
# ===========================================================================

class TestFailureTolerance:
    def test_one_failure_others_succeed(self):
        adapters = [
            FakeAdapter("a1", status=STATUS_SUCCESS, cost=0.01),
            FakeAdapter("a2", status=STATUS_FAILED),
            FakeAdapter("a3", status=STATUS_SUCCESS, cost=0.03),
        ]
        result = run_parallel_research(adapters, "q")

        assert result.success_count == 2
        assert result.failed_count == 1
        assert result.has_success is True
        assert result.all_failed is False

    def test_skipped_not_counted_as_failed(self):
        adapters = [
            FakeAdapter("a1", status=STATUS_SUCCESS),
            FakeAdapter("a2", status=STATUS_SKIPPED),
        ]
        result = run_parallel_research(adapters, "q")

        assert result.success_count == 1
        assert result.skipped_count == 1
        assert result.failed_count == 0
        assert result.has_success is True
        assert result.all_failed is False

    def test_exception_caught_and_converted_to_failed(self):
        """어댑터가 예외 던져도 러너가 포착해 FAILED로 변환."""
        adapters = [
            FakeAdapter("good", status=STATUS_SUCCESS),
            FakeAdapter("buggy", raise_exc=RuntimeError("oops")),
        ]
        result = run_parallel_research(adapters, "q")

        assert result.success_count == 1
        assert result.failed_count == 1
        # 예외는 FAILED로
        failed = result.failed[0]
        assert failed.adapter_name == "buggy"


# ===========================================================================
# C. 전부 실패 / 전부 스킵
# ===========================================================================

class TestAllFailedOrSkipped:
    def test_all_failed(self):
        adapters = [
            FakeAdapter("a1", status=STATUS_FAILED),
            FakeAdapter("a2", status=STATUS_FAILED),
            FakeAdapter("a3", status=STATUS_FAILED),
        ]
        result = run_parallel_research(adapters, "q")

        assert result.success_count == 0
        assert result.failed_count == 3
        assert result.has_success is False
        assert result.all_failed is True

    def test_all_skipped_not_considered_failed(self):
        """전부 skipped면 all_failed=False (시도 자체가 없었음)."""
        adapters = [
            FakeAdapter("a1", status=STATUS_SKIPPED),
            FakeAdapter("a2", status=STATUS_SKIPPED),
        ]
        result = run_parallel_research(adapters, "q")

        assert result.skipped_count == 2
        assert result.success_count == 0
        assert result.all_failed is False  # 스킵은 실패 아님
        assert result.has_success is False

    def test_mixed_skip_and_fail_all_failed_true(self):
        """skip 빼고 나머지가 다 fail이면 all_failed=True."""
        adapters = [
            FakeAdapter("a1", status=STATUS_SKIPPED),
            FakeAdapter("a2", status=STATUS_FAILED),
            FakeAdapter("a3", status=STATUS_FAILED),
        ]
        result = run_parallel_research(adapters, "q")

        assert result.success_count == 0
        assert result.failed_count == 2
        assert result.skipped_count == 1
        assert result.all_failed is True  # 시도된 2개가 전부 fail


# ===========================================================================
# D. 빈 어댑터 리스트
# ===========================================================================

class TestEmptyAdapters:
    def test_empty_list_returns_empty_result(self):
        result = run_parallel_research([], "q")
        assert result.query == "q"
        assert result.results == []
        assert result.success_count == 0
        assert result.has_success is False
        assert result.all_failed is False

    def test_empty_list_no_exception(self):
        """빈 리스트도 예외 안 던짐."""
        run_parallel_research([], "q")  # should not raise


# ===========================================================================
# E. 타임아웃
# ===========================================================================

class TestTimeout:
    def test_overall_timeout_exceeded(self):
        """전체 타임아웃보다 어댑터가 느리면 FAILED."""
        adapters = [
            FakeAdapter("slow", delay_sec=2.0, status=STATUS_SUCCESS),
        ]
        # 0.1초 타임아웃
        result = run_parallel_research(adapters, "q", timeout=0.1)

        # 느린 어댑터는 타임아웃으로 실패
        assert result.failed_count == 1
        failed = result.failed[0]
        assert "timeout" in (failed.error or "").lower()


# ===========================================================================
# F. 비용 집계
# ===========================================================================

class TestCostAggregation:
    def test_sum_of_costs(self):
        adapters = [
            FakeAdapter("a1", cost=0.1),
            FakeAdapter("a2", cost=0.2),
            FakeAdapter("a3", cost=0.3),
        ]
        result = run_parallel_research(adapters, "q")
        assert result.total_cost_usd == pytest.approx(0.6, abs=1e-6)

    def test_failed_adapter_cost_zero(self):
        """실패한 어댑터의 cost는 0으로 간주되어 총합에 영향 없음."""
        adapters = [
            FakeAdapter("a1", status=STATUS_SUCCESS, cost=0.1),
            FakeAdapter("a2", status=STATUS_FAILED, cost=0.0),
        ]
        result = run_parallel_research(adapters, "q")
        assert result.total_cost_usd == pytest.approx(0.1, abs=1e-6)


# ===========================================================================
# G. ParallelResult 필드 / to_dict
# ===========================================================================

class TestParallelResultStructure:
    def test_filters_by_status(self):
        adapters = [
            FakeAdapter("ok", status=STATUS_SUCCESS),
            FakeAdapter("bad", status=STATUS_FAILED),
            FakeAdapter("skip", status=STATUS_SKIPPED),
        ]
        result = run_parallel_research(adapters, "q")

        assert len(result.successful) == 1
        assert result.successful[0].adapter_name == "ok"
        assert len(result.failed) == 1
        assert result.failed[0].adapter_name == "bad"
        assert len(result.skipped) == 1
        assert result.skipped[0].adapter_name == "skip"

    def test_to_dict(self):
        adapters = [FakeAdapter("a1", cost=0.05)]
        result = run_parallel_research(adapters, "test query")

        d = result.to_dict()
        assert d["query"] == "test query"
        assert d["success_count"] == 1
        assert d["failed_count"] == 0
        assert d["skipped_count"] == 0
        assert d["total_cost_usd"] == pytest.approx(0.05)
        assert len(d["results"]) == 1
        assert isinstance(d["total_duration_ms"], int)


# ===========================================================================
# H. 내부 헬퍼
# ===========================================================================

class TestSafeResearch:
    def test_normal_path(self):
        adapter = FakeAdapter("a1", status=STATUS_SUCCESS)
        result = _safe_research(adapter, "q")
        assert result.status == STATUS_SUCCESS

    def test_exception_converted(self):
        """_safe_research는 예외를 FAILED로 변환."""
        adapter = FakeAdapter("a1", raise_exc=RuntimeError("boom"))
        # base.research()가 이미 예외를 잡는지 확인 필요. 
        # 만약 그게 아니라면 _safe_research가 잡음
        result = _safe_research(adapter, "q")
        assert result.status == STATUS_FAILED
        assert result.adapter_name == "a1"


class TestResolveOverallTimeout:
    def test_user_specified_wins(self):
        adapters = [FakeAdapter(timeout=100.0)]
        assert _resolve_overall_timeout(adapters, 5.0) == 5.0

    def test_default_is_max_plus_30(self):
        adapters = [
            FakeAdapter(timeout=60.0),
            FakeAdapter(timeout=300.0),
            FakeAdapter(timeout=120.0),
        ]
        assert _resolve_overall_timeout(adapters, None) == 330.0  # 300+30

    def test_empty_adapters_fallback(self):
        """어댑터 없으면 fallback 300초."""
        assert _resolve_overall_timeout([], None) == 300.0

    def test_zero_timeout_treated_as_none(self):
        """0 타임아웃은 무시하고 기본값 사용."""
        adapters = [FakeAdapter(timeout=60.0)]
        assert _resolve_overall_timeout(adapters, 0) == 90.0  # 60+30


# ===========================================================================
# I. build_default_adapters
# ===========================================================================

class TestBuildDefaultAdapters:
    def test_web_search_mode_creates_four(self):
        adapters = build_default_adapters(mode="web_search")
        assert len(adapters) == 4
        names = [getattr(a, "name", "") for a in adapters]
        # 각 이름이 예상 패턴인지
        assert any("perplexity" in n for n in names)
        assert any("openai" in n for n in names)
        assert any("gemini" in n for n in names)
        assert any("claude" in n for n in names)

    def test_deep_research_mode_claude_still_web(self):
        """Claude는 DR 지원 안 하므로 web_search만."""
        from src.research_v2.perplexity_adapter import MODE_DEEP_RESEARCH
        adapters = build_default_adapters(mode="deep_research")
        assert len(adapters) == 4

        # Perplexity/OpenAI/Gemini는 deep_research 모드
        for a in adapters[:3]:
            assert getattr(a, "mode", None) == "deep_research"

        # Claude는 mode 속성 없음 (단일 모드)
        claude = adapters[3]
        assert not hasattr(claude, "mode") or getattr(claude, "mode", None) is None


# ===========================================================================
# J. 실사용 시나리오 (실제 4개 어댑터 시뮬레이션)
# ===========================================================================

class TestRealisticScenario:
    def test_mixed_real_world(self):
        """실전: 1성공 + 1실패 + 1스킵."""
        adapters = [
            FakeAdapter("perplexity_research", status=STATUS_SUCCESS,
                        report="# Perplexity 보고서", cost=0.008, model="sonar-pro"),
            FakeAdapter("openai_research", status=STATUS_FAILED,
                        cost=0.0, model="gpt-5.4"),
            FakeAdapter("gemini_research", status=STATUS_SKIPPED,
                        cost=0.0, model="gemini-3.1-pro-preview"),
            FakeAdapter("claude_web_research", status=STATUS_SUCCESS,
                        report="# Claude 보고서", cost=0.012, model="claude-sonnet-4-6"),
        ]

        result = run_parallel_research(adapters, "커피 로스팅 가이드")

        assert result.success_count == 2
        assert result.failed_count == 1
        assert result.skipped_count == 1
        assert result.has_success is True
        assert result.all_failed is False
        # 0.008 + 0.012 = 0.020
        assert result.total_cost_usd == pytest.approx(0.020, abs=1e-6)

        # 성공한 어댑터 이름들
        success_names = [r.adapter_name for r in result.successful]
        assert "perplexity_research" in success_names
        assert "claude_web_research" in success_names
