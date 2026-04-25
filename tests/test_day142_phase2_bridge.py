"""
Day 142 — Phase 2 Bridge 테스트 (v3 포맷 호환).

검증:
  A. _convert_single — 단일 ResearchResult → v3 dict
  B. _to_v3_format — ParallelResult → 다중 어댑터 dict
  C. run_phase_2_research — 전체 흐름
  D. Phase2Result 구조 / to_dict
  E. AllSubtopicsFailedError
  F. 빈/잘못된 입력 방어
  G. 환경변수 모드 결정
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.research_v2.phase2_bridge import (
    Phase2Result,
    AllSubtopicsFailedError,
    run_phase_2_research,
    _to_v3_format,
    _convert_single,
)
from src.research_v2.parallel_runner import ParallelResult
from src.research_v2.base import (
    ResearchResult,
    ResearchCitation,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_SKIPPED,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_success(name="adapter_x", report="# 보고서", citations=None, cost=0.01):
    return ResearchResult(
        adapter_name=name,
        status=STATUS_SUCCESS,
        report=report,
        citations=citations or [],
        model="model-x",
        cost_usd=cost,
    )


def _make_failed(name="adapter_y", error="HTTP 500"):
    return ResearchResult(
        adapter_name=name,
        status=STATUS_FAILED,
        error=error,
    )


def _make_skipped(name="adapter_z"):
    return ResearchResult(
        adapter_name=name,
        status=STATUS_SKIPPED,
    )


def _make_parallel_result(query="q", results=None):
    return ParallelResult(
        query=query,
        results=results or [],
        total_duration_ms=100,
    )


# ===========================================================================
# A. _convert_single — 단일 변환
# ===========================================================================

class TestConvertSingle:
    def test_success_with_report_and_citations(self):
        r = _make_success(
            name="perplexity",
            report="# Coffee report",
            citations=[
                ResearchCitation(url="https://scaa.org", title="SCAA"),
                ResearchCitation(url="https://other.com"),
            ],
        )
        out = _convert_single(r)

        assert out["status"] == "success"
        assert out["error"] is None
        assert isinstance(out["claims"], list)
        assert len(out["claims"]) == 1
        assert out["claims"][0]["text"] == "# Coffee report"
        assert out["claims"][0]["source"] == "https://scaa.org"

    def test_success_no_citations_uses_adapter_name(self):
        r = _make_success(name="claude_web", report="report", citations=[])
        out = _convert_single(r)
        assert out["claims"][0]["source"] == "claude_web"

    def test_success_empty_citation_url_falls_back(self):
        """첫 citation URL이 비어 있으면 어댑터명 사용."""
        r = _make_success(
            name="openai",
            citations=[ResearchCitation(url="")],
        )
        out = _convert_single(r)
        assert out["claims"][0]["source"] == "openai"

    def test_success_empty_report_treated_as_failed(self):
        """report가 비었으면 success여도 failed로 처리."""
        r = _make_success(report="")
        out = _convert_single(r)
        assert out["status"] == "failed"
        assert out["claims"] is None
        assert "empty" in out["error"].lower()

    def test_success_whitespace_only_report(self):
        r = _make_success(report="   \n\n  ")
        out = _convert_single(r)
        assert out["status"] == "failed"

    def test_failed_status(self):
        r = _make_failed(name="gemini", error="timeout after 60s")
        out = _convert_single(r)
        assert out["status"] == "failed"
        assert out["claims"] is None
        assert out["error"] == "timeout after 60s"

    def test_failed_no_error_field(self):
        r = ResearchResult(adapter_name="x", status=STATUS_FAILED)
        out = _convert_single(r)
        assert out["error"] == "unknown error"

    def test_skipped(self):
        r = _make_skipped(name="claude_web")
        out = _convert_single(r)
        assert out["status"] == "skipped"
        assert out["claims"] is None
        assert out["error"] is None


# ===========================================================================
# B. _to_v3_format — 다중 어댑터 변환
# ===========================================================================

class TestToV3Format:
    def test_multiple_adapters(self):
        parallel = _make_parallel_result(results=[
            _make_success(name="perplexity_research", report="report A"),
            _make_failed(name="openai_research", error="rate limit"),
            _make_skipped(name="claude_web_research"),
        ])
        out = _to_v3_format(parallel)

        assert set(out.keys()) == {
            "perplexity_research", "openai_research", "claude_web_research",
        }
        assert out["perplexity_research"]["status"] == "success"
        assert out["openai_research"]["status"] == "failed"
        assert out["claude_web_research"]["status"] == "skipped"

    def test_empty_parallel_result(self):
        out = _to_v3_format(_make_parallel_result(results=[]))
        assert out == {}


# ===========================================================================
# C. run_phase_2_research — 전체 흐름
# ===========================================================================

class TestRunPhase2Research:
    def test_single_subtopic_all_adapters_success(self, monkeypatch):
        """모든 어댑터 성공 시나리오."""
        monkeypatch.delenv("PHASE_2_MODE", raising=False)

        # build_default_adapters 와 run_parallel_research mock
        mock_parallel = _make_parallel_result(
            query="커피",
            results=[
                _make_success(name="perplexity_research", report="P 보고서"),
                _make_success(name="openai_research", report="O 보고서"),
                _make_success(name="gemini_research", report="G 보고서"),
                _make_success(name="claude_web_research", report="C 보고서"),
            ],
        )

        with patch("src.research_v2.phase2_bridge.build_default_adapters") as mock_build, \
             patch("src.research_v2.phase2_bridge.run_parallel_research", return_value=mock_parallel):
            mock_build.return_value = []  # 어댑터 자체는 mock된 run_parallel이 사용 안 함
            result = run_phase_2_research(["커피"])

        assert result.total_subtopics == 1
        assert result.successful_subtopics == 1
        assert result.failed_subtopics == []
        assert result.total_adapter_calls == 4
        assert result.successful_adapter_calls == 4

        # data 구조 확인
        assert "커피" in result.data
        adapter_results = result.data["커피"]
        assert len(adapter_results) == 4
        assert all(r["status"] == "success" for r in adapter_results.values())

    def test_multiple_subtopics(self, monkeypatch):
        """3개 서브토픽 각각 다른 결과."""
        monkeypatch.delenv("PHASE_2_MODE", raising=False)

        # 호출마다 다른 결과 반환
        def side_effect(adapters, query, **kwargs):
            if query == "topic1":
                return _make_parallel_result(query=query, results=[
                    _make_success(name="perplexity_research"),
                    _make_failed(name="openai_research"),
                ])
            elif query == "topic2":
                return _make_parallel_result(query=query, results=[
                    _make_success(name="perplexity_research"),
                    _make_success(name="openai_research"),
                ])
            else:  # topic3 — 전부 실패
                return _make_parallel_result(query=query, results=[
                    _make_failed(name="perplexity_research"),
                    _make_failed(name="openai_research"),
                ])

        with patch("src.research_v2.phase2_bridge.build_default_adapters", return_value=[]), \
             patch("src.research_v2.phase2_bridge.run_parallel_research", side_effect=side_effect):
            result = run_phase_2_research(["topic1", "topic2", "topic3"])

        assert result.total_subtopics == 3
        assert result.successful_subtopics == 2  # topic1, topic2
        assert result.failed_subtopics == ["topic3"]
        assert result.total_adapter_calls == 6  # 2+2+2
        assert result.successful_adapter_calls == 3  # 1+2+0

    def test_subtopic_with_partial_success_counted_as_successful(self, monkeypatch):
        """1개 어댑터만 성공해도 subtopic은 successful."""
        mock_parallel = _make_parallel_result(results=[
            _make_failed(name="perplexity_research"),
            _make_success(name="openai_research"),
            _make_failed(name="gemini_research"),
        ])

        with patch("src.research_v2.phase2_bridge.build_default_adapters", return_value=[]), \
             patch("src.research_v2.phase2_bridge.run_parallel_research", return_value=mock_parallel):
            result = run_phase_2_research(["q"])

        assert result.successful_subtopics == 1
        assert result.failed_subtopics == []

    def test_skipped_only_subtopic_not_counted_as_failed(self, monkeypatch):
        """전부 skipped인 subtopic은 failed로 안 침 (시도 자체 없음)."""
        mock_parallel = _make_parallel_result(results=[
            _make_skipped(name="perplexity_research"),
            _make_skipped(name="openai_research"),
        ])

        with patch("src.research_v2.phase2_bridge.build_default_adapters", return_value=[]), \
             patch("src.research_v2.phase2_bridge.run_parallel_research", return_value=mock_parallel):
            result = run_phase_2_research(["q"])

        assert result.successful_subtopics == 0
        assert result.failed_subtopics == []  # 시도 안 됐으므로 실패도 아님


# ===========================================================================
# D. Phase2Result.to_dict
# ===========================================================================

class TestPhase2ResultStructure:
    def test_to_dict_full(self):
        result = Phase2Result(
            total_subtopics=2,
            successful_subtopics=1,
            failed_subtopics=["bad_topic"],
            total_adapter_calls=8,
            successful_adapter_calls=4,
            total_cost_usd=0.15,
        )
        result.data = {
            "good_topic": {"perplexity_research": {"status": "success"}},
            "bad_topic": {"perplexity_research": {"status": "failed"}},
        }

        d = result.to_dict()
        assert d["total_subtopics"] == 2
        assert d["successful_subtopics"] == 1
        assert d["failed_subtopics"] == ["bad_topic"]
        assert d["total_adapter_calls"] == 8
        assert d["successful_adapter_calls"] == 4
        assert d["total_cost_usd"] == 0.15
        assert "good_topic" in d["data"]


# ===========================================================================
# E. AllSubtopicsFailedError
# ===========================================================================

class TestAllSubtopicsFailedError:
    def test_all_failed_raises(self, monkeypatch):
        """모든 subtopic이 시도됐고 전부 실패면 예외."""
        mock_parallel = _make_parallel_result(results=[
            _make_failed(name="perplexity_research"),
            _make_failed(name="openai_research"),
        ])

        with patch("src.research_v2.phase2_bridge.build_default_adapters", return_value=[]), \
             patch("src.research_v2.phase2_bridge.run_parallel_research", return_value=mock_parallel):
            with pytest.raises(AllSubtopicsFailedError, match="모든 subtopic"):
                run_phase_2_research(["t1", "t2"])

    def test_all_skipped_does_not_raise(self, monkeypatch):
        """전부 skipped면 예외 안 던짐 (시도 자체 없음)."""
        mock_parallel = _make_parallel_result(results=[
            _make_skipped(name="perplexity_research"),
            _make_skipped(name="openai_research"),
        ])

        with patch("src.research_v2.phase2_bridge.build_default_adapters", return_value=[]), \
             patch("src.research_v2.phase2_bridge.run_parallel_research", return_value=mock_parallel):
            # 예외 없이 실행되어야
            result = run_phase_2_research(["t1", "t2"])
            assert result.successful_subtopics == 0
            assert result.successful_adapter_calls == 0


# ===========================================================================
# F. 잘못된 입력 방어
# ===========================================================================

class TestInputValidation:
    def test_empty_subtopics_raises(self):
        with pytest.raises(ValueError, match="빈 리스트"):
            run_phase_2_research([])


# ===========================================================================
# G. 환경변수 모드 결정
# ===========================================================================

class TestModeResolution:
    def test_default_web_search(self, monkeypatch):
        monkeypatch.delenv("PHASE_2_MODE", raising=False)
        captured = {}

        def capture_build(mode="web_search"):
            captured["mode"] = mode
            return []

        mock_parallel = _make_parallel_result(results=[
            _make_success(name="perplexity_research"),
        ])

        with patch("src.research_v2.phase2_bridge.build_default_adapters", side_effect=capture_build), \
             patch("src.research_v2.phase2_bridge.run_parallel_research", return_value=mock_parallel):
            run_phase_2_research(["q"])

        assert captured["mode"] == "web_search"

    def test_env_var_deep_research(self, monkeypatch):
        monkeypatch.setenv("PHASE_2_MODE", "deep_research")
        captured = {}

        def capture_build(mode="web_search"):
            captured["mode"] = mode
            return []

        mock_parallel = _make_parallel_result(results=[
            _make_success(name="perplexity_research"),
        ])

        with patch("src.research_v2.phase2_bridge.build_default_adapters", side_effect=capture_build), \
             patch("src.research_v2.phase2_bridge.run_parallel_research", return_value=mock_parallel):
            run_phase_2_research(["q"])

        assert captured["mode"] == "deep_research"

    def test_explicit_mode_overrides_env(self, monkeypatch):
        monkeypatch.setenv("PHASE_2_MODE", "deep_research")
        captured = {}

        def capture_build(mode="web_search"):
            captured["mode"] = mode
            return []

        mock_parallel = _make_parallel_result(results=[
            _make_success(name="perplexity_research"),
        ])

        with patch("src.research_v2.phase2_bridge.build_default_adapters", side_effect=capture_build), \
             patch("src.research_v2.phase2_bridge.run_parallel_research", return_value=mock_parallel):
            run_phase_2_research(["q"], mode="web_search")

        assert captured["mode"] == "web_search"

    def test_invalid_env_falls_back_to_web_search(self, monkeypatch):
        monkeypatch.setenv("PHASE_2_MODE", "garbage")
        captured = {}

        def capture_build(mode="web_search"):
            captured["mode"] = mode
            return []

        mock_parallel = _make_parallel_result(results=[
            _make_success(name="perplexity_research"),
        ])

        with patch("src.research_v2.phase2_bridge.build_default_adapters", side_effect=capture_build), \
             patch("src.research_v2.phase2_bridge.run_parallel_research", return_value=mock_parallel):
            run_phase_2_research(["q"])

        assert captured["mode"] == "web_search"


# ===========================================================================
# H. 실사용 시나리오 — Phase 3 인터페이스 호환성
# ===========================================================================

class TestPhase3Compatibility:
    def test_output_matches_phase3_input_shape(self, monkeypatch):
        """
        실제 phase_3_synthesize.py가 사용하는 패턴:
          for subtopic, adapters in parallel_research.items():
              for adapter_name, adapter_result in adapters.items():
                  if adapter_result.get("status") != "success": continue
                  claims = adapter_result.get("claims") or []
                  for c in claims:
                      text = c.get("text", "")
                      source = c.get("source", "")
        """
        mock_parallel = _make_parallel_result(results=[
            _make_success(
                name="perplexity_research",
                report="# 커피 로스팅\n\n핵심 단계는...",
                citations=[ResearchCitation(url="https://scaa.org", title="SCAA")],
            ),
            _make_success(
                name="openai_research",
                report="OpenAI report",
                citations=[],
            ),
        ])

        with patch("src.research_v2.phase2_bridge.build_default_adapters", return_value=[]), \
             patch("src.research_v2.phase2_bridge.run_parallel_research", return_value=mock_parallel):
            result = run_phase_2_research(["커피 로스팅"])

        # Phase 3 패턴 시뮬레이션
        parallel_research = result.data
        all_extracted = []

        for subtopic, adapters in parallel_research.items():
            for adapter_name, adapter_result in adapters.items():
                if adapter_result.get("status") != "success":
                    continue
                claims = adapter_result.get("claims") or []
                for c in claims:
                    text = c.get("text", "") if isinstance(c, dict) else str(c)
                    source = c.get("source", "") if isinstance(c, dict) else ""
                    if text:
                        all_extracted.append((subtopic, adapter_name, text, source))

        # 2개 어댑터 × 1 claim씩 = 2개
        assert len(all_extracted) == 2
        # 각 텍스트가 report 내용과 일치하는지
        texts = {x[2] for x in all_extracted}
        assert "# 커피 로스팅\n\n핵심 단계는..." in texts
        assert "OpenAI report" in texts

        # source가 의미 있는 값
        sources = {x[3] for x in all_extracted}
        assert "https://scaa.org" in sources  # citation URL 우선
        assert "openai_research" in sources    # citation 없으면 어댑터명
