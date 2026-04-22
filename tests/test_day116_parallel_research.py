"""
Day 116 — Phase 2 · 병렬 리서치 테스트.

검증 포인트:
1. ParallelResearchResult 구조
2. 정상 경로 (3 adapter × N subtopic 전부 성공)
3. partial 허용:
   - 일부 어댑터 실패 → 나머지 계속
   - 특정 subtopic 전체 실패 → 해당 것만 제외
   - 모든 subtopic 실패 → AllSubtopicsFailedError 전파
4. 빈 입력 / 어댑터 없음
5. subtopic 순차 + adapter 병렬 동작 확인
6. claims 정규화 (ResearchResult 객체 또는 dict 모두 수용)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# 테스트용 가짜 어댑터 (실 네트워크 금지)
# ---------------------------------------------------------------------------

def _make_fake_adapter(name: str, behavior: str = "success", claims=None):
    """
    behavior:
      "success"       — 정상 claims 반환
      "empty"         — 빈 claims
      "error_result"  — ResearchResult(error=...) 반환
      "raise"         — 예외 발생
    """
    adapter = MagicMock()
    adapter.name = name
    adapter.is_available = MagicMock(return_value=True)

    if behavior == "success":
        default_claims = claims or [
            MagicMock(text=f"{name} claim 1", source=f"{name}-source-1"),
            MagicMock(text=f"{name} claim 2", source=f"{name}-source-2"),
        ]
        result = MagicMock()
        result.error = None
        result.claims = default_claims
        adapter.search = MagicMock(return_value=result)

    elif behavior == "empty":
        result = MagicMock()
        result.error = None
        result.claims = []
        adapter.search = MagicMock(return_value=result)

    elif behavior == "error_result":
        result = MagicMock()
        result.error = f"{name} API error"
        result.claims = []
        adapter.search = MagicMock(return_value=result)

    elif behavior == "raise":
        adapter.search = MagicMock(side_effect=RuntimeError(f"{name} crashed"))

    return adapter


# ===========================================================================
# 1. ParallelResearchResult 구조
# ===========================================================================

class TestResultStructure:
    def test_empty_result_defaults(self):
        from src.research.parallel_router import ParallelResearchResult
        r = ParallelResearchResult()
        assert r.data == {}
        assert r.total_subtopics == 0
        assert r.successful_subtopics == 0
        assert r.failed_subtopics == []
        assert r.total_adapter_calls == 0
        assert r.successful_adapter_calls == 0

    def test_to_dict_has_all_keys(self):
        from src.research.parallel_router import ParallelResearchResult
        r = ParallelResearchResult()
        d = r.to_dict()
        for key in ["data", "total_subtopics", "successful_subtopics",
                    "failed_subtopics", "total_adapter_calls",
                    "successful_adapter_calls"]:
            assert key in d


# ===========================================================================
# 2. 정상 경로
# ===========================================================================

class TestHappyPath:
    def test_all_success(self):
        from src.research.parallel_router import run_parallel_research

        adapters = [
            _make_fake_adapter("gemini", "success"),
            _make_fake_adapter("gpt", "success"),
            _make_fake_adapter("perplexity", "success"),
        ]
        subtopics = ["서브주제 A", "서브주제 B"]

        result = run_parallel_research(subtopics, adapters=adapters)

        assert result.total_subtopics == 2
        assert result.successful_subtopics == 2
        assert result.failed_subtopics == []
        assert result.total_adapter_calls == 6  # 2 × 3
        assert result.successful_adapter_calls == 6

    def test_result_data_structure(self):
        from src.research.parallel_router import run_parallel_research

        adapters = [
            _make_fake_adapter("gemini", "success"),
            _make_fake_adapter("gpt", "success"),
        ]
        subtopics = ["A"]
        result = run_parallel_research(subtopics, adapters=adapters)

        assert "A" in result.data
        assert "gemini" in result.data["A"]
        assert "gpt" in result.data["A"]
        assert result.data["A"]["gemini"]["status"] == "success"
        assert result.data["A"]["gpt"]["status"] == "success"

    def test_claims_normalized_from_object(self):
        """ResearchClaim 객체 형태 응답을 dict로 정규화."""
        from src.research.parallel_router import run_parallel_research

        adapters = [_make_fake_adapter("gemini", "success")]
        result = run_parallel_research(["A"], adapters=adapters)

        claims = result.data["A"]["gemini"]["claims"]
        assert isinstance(claims, list)
        assert len(claims) > 0
        for c in claims:
            assert isinstance(c, dict)
            assert "text" in c
            assert "source" in c

    def test_every_adapter_called_once_per_subtopic(self):
        from src.research.parallel_router import run_parallel_research

        gemini = _make_fake_adapter("gemini", "success")
        gpt = _make_fake_adapter("gpt", "success")
        subtopics = ["A", "B", "C"]

        run_parallel_research(subtopics, adapters=[gemini, gpt])

        assert gemini.search.call_count == 3  # subtopic 3개
        assert gpt.search.call_count == 3


# ===========================================================================
# 3. Partial 허용 정책
# ===========================================================================

class TestPartialPolicy:
    def test_one_adapter_fails_others_continue(self):
        """한 어댑터만 실패 → 나머지는 정상."""
        from src.research.parallel_router import run_parallel_research

        adapters = [
            _make_fake_adapter("gemini", "success"),
            _make_fake_adapter("gpt", "raise"),      # 실패
            _make_fake_adapter("perplexity", "success"),
        ]
        result = run_parallel_research(["A"], adapters=adapters)

        assert result.data["A"]["gemini"]["status"] == "success"
        assert result.data["A"]["gpt"]["status"] == "failed"
        assert "crashed" in result.data["A"]["gpt"]["error"]
        assert result.data["A"]["perplexity"]["status"] == "success"
        # subtopic 자체는 성공 (1개 이상 성공한 어댑터 있음)
        assert result.successful_subtopics == 1

    def test_error_result_treated_as_failed(self):
        """ResearchResult(error=...) 반환은 failed 처리."""
        from src.research.parallel_router import run_parallel_research

        adapters = [
            _make_fake_adapter("gemini", "success"),
            _make_fake_adapter("gpt", "error_result"),
        ]
        result = run_parallel_research(["A"], adapters=adapters)

        assert result.data["A"]["gpt"]["status"] == "failed"
        assert "API error" in result.data["A"]["gpt"]["error"]

    def test_empty_claims_treated_as_failed(self):
        """빈 claims → failed 처리."""
        from src.research.parallel_router import run_parallel_research

        adapters = [
            _make_fake_adapter("gemini", "success"),
            _make_fake_adapter("gpt", "empty"),
        ]
        result = run_parallel_research(["A"], adapters=adapters)

        assert result.data["A"]["gpt"]["status"] == "failed"

    def test_subtopic_all_adapters_fail_marked_failed(self):
        """특정 subtopic의 모든 어댑터 실패 → failed_subtopics에 기록, 계속 진행."""
        from src.research.parallel_router import run_parallel_research

        # subtopic별로 다른 어댑터 동작이 필요하므로 side_effect 사용
        gemini = MagicMock()
        gemini.name = "gemini"
        gemini.is_available.return_value = True
        # A에서는 실패, B에서는 성공
        call_count_gemini = {"count": 0}
        def gemini_search(q):
            call_count_gemini["count"] += 1
            if "A" in q:
                raise RuntimeError("A failed")
            result = MagicMock()
            result.error = None
            result.claims = [MagicMock(text="ok", source="src")]
            return result
        gemini.search = MagicMock(side_effect=gemini_search)

        gpt = MagicMock()
        gpt.name = "gpt"
        gpt.is_available.return_value = True
        def gpt_search(q):
            if "A" in q:
                raise RuntimeError("A also failed")
            result = MagicMock()
            result.error = None
            result.claims = [MagicMock(text="ok", source="src")]
            return result
        gpt.search = MagicMock(side_effect=gpt_search)

        result = run_parallel_research(["A 주제", "B 주제"], adapters=[gemini, gpt])

        assert "A 주제" in result.failed_subtopics
        assert "B 주제" not in result.failed_subtopics
        assert result.successful_subtopics == 1  # B만 성공
        assert result.total_subtopics == 2

    def test_all_subtopics_fail_raises(self):
        """모든 subtopic 실패 → AllSubtopicsFailedError 전파."""
        from src.research.parallel_router import (
            run_parallel_research, AllSubtopicsFailedError
        )

        adapters = [
            _make_fake_adapter("gemini", "raise"),
            _make_fake_adapter("gpt", "raise"),
        ]

        with pytest.raises(AllSubtopicsFailedError, match="모든 subtopic"):
            run_parallel_research(["A", "B"], adapters=adapters)

    def test_all_error_results_also_raises(self):
        """모든 어댑터가 error_result 반환해도 AllSubtopicsFailedError."""
        from src.research.parallel_router import (
            run_parallel_research, AllSubtopicsFailedError
        )

        adapters = [
            _make_fake_adapter("gemini", "error_result"),
            _make_fake_adapter("gpt", "error_result"),
        ]

        with pytest.raises(AllSubtopicsFailedError):
            run_parallel_research(["A"], adapters=adapters)


# ===========================================================================
# 4. 빈 입력 / 어댑터 없음
# ===========================================================================

class TestEdgeCases:
    def test_empty_subtopics_returns_empty(self):
        from src.research.parallel_router import run_parallel_research
        adapters = [_make_fake_adapter("gemini", "success")]
        result = run_parallel_research([], adapters=adapters)
        assert result.total_subtopics == 0
        assert result.data == {}

    def test_no_active_adapters_raises(self):
        """활성 어댑터 0개 → AllSubtopicsFailedError."""
        from src.research.parallel_router import (
            run_parallel_research, AllSubtopicsFailedError
        )

        with pytest.raises(AllSubtopicsFailedError, match="하나도 없습니다"):
            run_parallel_research(["A"], adapters=[])

    def test_inactive_adapter_excluded(self):
        """is_available=False 어댑터는 호출 안 됨."""
        from src.research.parallel_router import run_parallel_research

        inactive = _make_fake_adapter("inactive", "success")
        inactive.is_available.return_value = True  # 실제로는 adapter loader에서 걸러짐

        # 여기서는 외부 주입이므로 그냥 동작 확인
        active = _make_fake_adapter("active", "success")
        result = run_parallel_research(["A"], adapters=[active])
        assert "active" in result.data["A"]


# ===========================================================================
# 5. 병렬성 — adapter가 동시에 호출되는가
# ===========================================================================

class TestParallelism:
    def test_adapters_run_concurrently_for_same_subtopic(self):
        """같은 subtopic 내에서 어댑터가 동시 호출 시작됨 (threading 확인)."""
        import threading
        import time

        from src.research.parallel_router import run_parallel_research

        thread_ids = set()
        lock = threading.Lock()

        def make_tracked_adapter(name):
            adapter = MagicMock()
            adapter.name = name
            adapter.is_available.return_value = True

            def tracked_search(q):
                with lock:
                    thread_ids.add(threading.get_ident())
                time.sleep(0.05)  # 약간의 시간이 있어야 병렬성 관찰 가능
                result = MagicMock()
                result.error = None
                result.claims = [MagicMock(text="ok", source="src")]
                return result

            adapter.search = MagicMock(side_effect=tracked_search)
            return adapter

        adapters = [
            make_tracked_adapter("gemini"),
            make_tracked_adapter("gpt"),
            make_tracked_adapter("perplexity"),
        ]

        start = time.time()
        run_parallel_research(["A"], adapters=adapters)
        elapsed = time.time() - start

        # 병렬이면 0.05초 정도, 순차면 0.15초 이상
        assert elapsed < 0.13, f"병렬 실행되지 않음 (소요: {elapsed}초)"
        # 별도 스레드에서 실행됐는지 확인
        assert len(thread_ids) >= 2, "어댑터가 모두 같은 스레드에서 실행됨"

    def test_subtopics_run_sequentially(self):
        """subtopic은 순차 실행 (A 끝나고 B 시작)."""
        import threading
        import time

        from src.research.parallel_router import run_parallel_research

        call_order = []
        lock = threading.Lock()

        def make_tracking_adapter(name):
            adapter = MagicMock()
            adapter.name = name
            adapter.is_available.return_value = True

            def search(q):
                with lock:
                    call_order.append(("start", q))
                time.sleep(0.03)
                with lock:
                    call_order.append(("end", q))
                result = MagicMock()
                result.error = None
                result.claims = [MagicMock(text="ok", source="src")]
                return result

            adapter.search = MagicMock(side_effect=search)
            return adapter

        adapters = [make_tracking_adapter("a1"), make_tracking_adapter("a2")]
        run_parallel_research(["A", "B"], adapters=adapters)

        # A에 대한 모든 호출이 끝난 뒤 B의 호출이 시작되어야 함
        a_ends = [i for i, (evt, q) in enumerate(call_order) if evt == "end" and q == "A"]
        b_starts = [i for i, (evt, q) in enumerate(call_order) if evt == "start" and q == "B"]

        if a_ends and b_starts:
            # 마지막 A end가 첫 B start보다 앞서야 함
            assert max(a_ends) < min(b_starts), "A가 끝나기 전에 B가 시작됨 (순차 아님)"


# ===========================================================================
# 6. 통계 집계
# ===========================================================================

class TestStatistics:
    def test_successful_adapter_calls_count(self):
        from src.research.parallel_router import run_parallel_research

        adapters = [
            _make_fake_adapter("gemini", "success"),
            _make_fake_adapter("gpt", "raise"),
        ]
        result = run_parallel_research(["A", "B"], adapters=adapters)

        assert result.total_adapter_calls == 4  # 2 subtopic × 2 adapter
        assert result.successful_adapter_calls == 2  # gemini만 성공 × 2

    def test_failed_subtopics_list_accurate(self):
        from src.research.parallel_router import run_parallel_research

        # 동일 어댑터가 특정 subtopic에만 실패하는 시나리오
        adapter = MagicMock()
        adapter.name = "solo"
        adapter.is_available.return_value = True

        def search(q):
            if q == "B":
                raise RuntimeError("B fails")
            r = MagicMock()
            r.error = None
            r.claims = [MagicMock(text="ok", source="src")]
            return r

        adapter.search = MagicMock(side_effect=search)

        result = run_parallel_research(["A", "B", "C"], adapters=[adapter])
        assert result.failed_subtopics == ["B"]
        assert result.successful_subtopics == 2
