"""
Day 137 — research_v2 추상 기반 테스트 (Phase 2 재구성 단계 1)

테스트 포인트:
  1. ResearchCitation / ResearchResult 스키마 왕복
  2. ResearchAdapter 추상성 (직접 인스턴스화 불가)
  3. FakeAdapter로 공통 research() 흐름 검증
     - is_available False → skipped
     - 빈 query → failed
     - 정상 실행 → success
     - 예외 발생 → failed (전파 없음)
     - 빈 report → failed
  4. duration_ms 측정
  5. to_dict / from_dict 왕복
"""
from __future__ import annotations

import pytest

from src.research_v2 import (
    ResearchAdapter,
    ResearchResult,
    ResearchCitation,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_SKIPPED,
)


# ===========================================================================
# 테스트용 Fake 어댑터
# ===========================================================================

class _FakeAdapter(ResearchAdapter):
    """테스트 전용 — 동작을 flag로 제어."""
    name = "fake"
    default_timeout = 5.0

    def __init__(
        self,
        available: bool = True,
        raise_exc: bool = False,
        empty_report: bool = False,
    ):
        self._available = available
        self._raise = raise_exc
        self._empty = empty_report

    def is_available(self) -> bool:
        return self._available

    def _do_research(self, query: str, timeout: float) -> ResearchResult:
        if self._raise:
            raise RuntimeError("simulated failure")
        report = "" if self._empty else f"report for: {query}"
        return ResearchResult(
            adapter_name=self.name,
            status=STATUS_SUCCESS,
            report=report,
            citations=[
                ResearchCitation(url="https://example.com", title="Ex", snippet="Hi"),
            ],
            model="fake-model-v1",
            cost_usd=0.01,
        )


# ===========================================================================
# 1. 스키마 — ResearchCitation
# ===========================================================================

class TestResearchCitation:
    def test_basic_roundtrip(self):
        c = ResearchCitation(
            url="https://foo.bar",
            title="Foo",
            snippet="snippet text",
        )
        d = c.to_dict()
        restored = ResearchCitation.from_dict(d)
        assert restored == c

    def test_empty_fields_default(self):
        c = ResearchCitation(url="https://x.com")
        assert c.title == ""
        assert c.snippet == ""

    def test_from_dict_partial(self):
        c = ResearchCitation.from_dict({"url": "https://a"})
        assert c.url == "https://a"
        assert c.title == ""

    def test_from_dict_coerces_types(self):
        c = ResearchCitation.from_dict({"url": 123, "title": None})
        assert c.url == "123"
        assert c.title == "None"


# ===========================================================================
# 2. 스키마 — ResearchResult
# ===========================================================================

class TestResearchResult:
    def test_default_is_skipped(self):
        r = ResearchResult(adapter_name="x")
        assert r.status == STATUS_SKIPPED
        assert r.is_success is False

    def test_success_requires_report(self):
        r = ResearchResult(
            adapter_name="x",
            status=STATUS_SUCCESS,
            report="content",
        )
        assert r.is_success is True

    def test_success_empty_report_not_success(self):
        r = ResearchResult(
            adapter_name="x",
            status=STATUS_SUCCESS,
            report="",
        )
        # is_success 는 report 비면 False
        assert r.is_success is False

    def test_to_dict_from_dict_roundtrip(self):
        original = ResearchResult(
            adapter_name="perplexity",
            status=STATUS_SUCCESS,
            report="# Report\n...",
            citations=[
                ResearchCitation(url="https://a", title="A"),
                ResearchCitation(url="https://b", title="B", snippet="b snippet"),
            ],
            model="sonar-deep-research",
            duration_ms=4500,
            cost_usd=1.23,
        )
        d = original.to_dict()
        restored = ResearchResult.from_dict(d)

        assert restored.adapter_name == original.adapter_name
        assert restored.status == original.status
        assert restored.report == original.report
        assert len(restored.citations) == 2
        assert restored.citations[0].url == "https://a"
        assert restored.citations[1].snippet == "b snippet"
        assert restored.model == original.model
        assert restored.duration_ms == 4500
        assert restored.cost_usd == pytest.approx(1.23)

    def test_from_dict_rejects_malformed_citations(self):
        """citations에 non-dict 섞여있어도 무시."""
        d = {
            "adapter_name": "x",
            "citations": [
                {"url": "https://a"},
                "not a dict",
                None,
                {"url": "https://b"},
            ],
        }
        r = ResearchResult.from_dict(d)
        assert len(r.citations) == 2

    def test_from_dict_defensive_defaults(self):
        r = ResearchResult.from_dict({})
        assert r.adapter_name == ""
        assert r.status == STATUS_SKIPPED
        assert r.cost_usd == 0.0
        assert r.citations == []

    def test_cost_rounded_to_6_decimal(self):
        r = ResearchResult(
            adapter_name="x",
            status=STATUS_SUCCESS,
            report="ok",
            cost_usd=0.123456789,
        )
        d = r.to_dict()
        assert d["cost_usd"] == 0.123457  # 6자리 반올림


# ===========================================================================
# 3. 추상 클래스
# ===========================================================================

class TestAbstractness:
    def test_cannot_instantiate_base(self):
        with pytest.raises(TypeError):
            ResearchAdapter()

    def test_subclass_without_methods_fails(self):
        class Incomplete(ResearchAdapter):
            name = "incomplete"
            # is_available, _do_research 없음

        with pytest.raises(TypeError):
            Incomplete()


# ===========================================================================
# 4. research() 공통 흐름
# ===========================================================================

class TestResearchFlow:
    def test_unavailable_returns_skipped(self):
        adapter = _FakeAdapter(available=False)
        result = adapter.research("test query")
        assert result.status == STATUS_SKIPPED
        assert result.adapter_name == "fake"
        assert "not_available" in (result.error or "")

    def test_empty_query_returns_failed(self):
        adapter = _FakeAdapter()
        assert adapter.research("").status == STATUS_FAILED
        assert adapter.research("   ").status == STATUS_FAILED

    def test_none_query_returns_failed(self):
        adapter = _FakeAdapter()
        assert adapter.research(None).status == STATUS_FAILED

    def test_successful_research(self):
        adapter = _FakeAdapter()
        result = adapter.research("coffee roasting")
        assert result.status == STATUS_SUCCESS
        assert "coffee roasting" in result.report
        assert len(result.citations) == 1
        assert result.model == "fake-model-v1"
        assert result.duration_ms >= 0

    def test_exception_caught_as_failed(self):
        adapter = _FakeAdapter(raise_exc=True)
        result = adapter.research("query")
        assert result.status == STATUS_FAILED
        assert "RuntimeError" in (result.error or "")
        # 예외 전파되지 않았음 — 여기까지 도달한 것이 검증

    def test_empty_report_success_downgraded(self):
        adapter = _FakeAdapter(empty_report=True)
        result = adapter.research("q")
        assert result.status == STATUS_FAILED
        assert "empty report" in (result.error or "")

    def test_duration_measured_even_on_failure(self):
        adapter = _FakeAdapter(raise_exc=True)
        result = adapter.research("q")
        assert result.duration_ms >= 0

    def test_query_trimmed_before_call(self):
        """_do_research 는 trimmed query 받아야."""
        class CaptureAdapter(ResearchAdapter):
            name = "capture"
            captured = None

            def is_available(self) -> bool:
                return True

            def _do_research(self, query: str, timeout: float) -> ResearchResult:
                CaptureAdapter.captured = query
                return ResearchResult(
                    adapter_name=self.name,
                    status=STATUS_SUCCESS,
                    report="r",
                )

        a = CaptureAdapter()
        a.research("   whitespace around   ")
        assert CaptureAdapter.captured == "whitespace around"

    def test_custom_timeout_passed(self):
        """research(timeout=...) 가 _do_research 에 전달."""
        class TimeoutAdapter(ResearchAdapter):
            name = "timeout"
            captured_timeout = None

            def is_available(self) -> bool:
                return True

            def _do_research(self, query: str, timeout: float) -> ResearchResult:
                TimeoutAdapter.captured_timeout = timeout
                return ResearchResult(
                    adapter_name=self.name, status=STATUS_SUCCESS, report="ok",
                )

        a = TimeoutAdapter()
        a.research("q", timeout=7.5)
        assert TimeoutAdapter.captured_timeout == 7.5

    def test_default_timeout_used_when_none(self):
        class DefaultTimeout(ResearchAdapter):
            name = "dt"
            default_timeout = 42.0
            captured = None

            def is_available(self) -> bool:
                return True

            def _do_research(self, query: str, timeout: float) -> ResearchResult:
                DefaultTimeout.captured = timeout
                return ResearchResult(
                    adapter_name=self.name, status=STATUS_SUCCESS, report="ok",
                )

        DefaultTimeout().research("q")
        assert DefaultTimeout.captured == 42.0
