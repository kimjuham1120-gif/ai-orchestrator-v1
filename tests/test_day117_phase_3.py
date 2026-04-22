"""
Day 117 — Phase 3 · 2문서 합성 테스트.

패치 방식: src.phases.phase_3_synthesize.call_llm 을 직접 mock
  → llm_utils의 재시도 로직과 충돌하지 않음
  → 테스트가 구현 내부(httpx) 에 결합되지 않음

검증 포인트:
1. SynthesizeResult 구조
2. 리서치 요약 포맷
3. 정상 경로 (3a + 3b 모두 성공)
4. 독립 실패 (3a 실패해도 3b 성공)
5. 둘 다 실패 (에러 병합)
6. 입력 검증 (빈 raw_input, 빈 parallel_research, 성공 리서치 없음)
7. API 키 없을 때
8. 마크다운 래퍼 제거
9. any_success 프로퍼티
"""
from __future__ import annotations

import pytest
from unittest.mock import patch


# call_llm 패치 경로 — phase_3_synthesize 모듈이 import한 심볼을 mock
_CALL_LLM_PATCH = "src.phases.phase_3_synthesize.call_llm"


# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------

def _sample_parallel_research():
    """테스트용 Phase 2 결과 샘플."""
    return {
        "작성 방법론": {
            "gemini": {
                "status": "success",
                "claims": [
                    {"text": "사업계획서 핵심 요소 5가지", "source": "공식문서"},
                    {"text": "경영진 요약 작성법", "source": "기술블로그"},
                ],
                "error": None,
            },
            "gpt": {
                "status": "success",
                "claims": [{"text": "1페이지 요약의 중요성", "source": "aicoach"}],
                "error": None,
            },
        },
        "시장 조사": {
            "gemini": {
                "status": "success",
                "claims": [{"text": "2026 시장 규모 10조", "source": "통계청"}],
                "error": None,
            },
            "perplexity": {
                "status": "failed",
                "claims": None,
                "error": "timeout",
            },
        },
    }


# ===========================================================================
# 1. 결과 타입 구조
# ===========================================================================

class TestResultStructure:
    def test_empty_result_defaults(self):
        from src.phases.phase_3_synthesize import SynthesizeResult, STATUS_SKIPPED
        r = SynthesizeResult()
        assert r.base_info_doc is None
        assert r.target_doc is None
        assert r.base_info_status == STATUS_SKIPPED
        assert r.target_doc_status == STATUS_SKIPPED
        assert r.error is None

    def test_to_dict_has_all_keys(self):
        from src.phases.phase_3_synthesize import SynthesizeResult
        r = SynthesizeResult()
        d = r.to_dict()
        for key in ["base_info_doc", "target_doc",
                    "base_info_status", "target_doc_status", "error"]:
            assert key in d

    def test_any_success_property_false_by_default(self):
        from src.phases.phase_3_synthesize import SynthesizeResult
        r = SynthesizeResult()
        assert r.any_success is False

    def test_any_success_true_when_base_success(self):
        from src.phases.phase_3_synthesize import SynthesizeResult, STATUS_SUCCESS
        r = SynthesizeResult(base_info_status=STATUS_SUCCESS)
        assert r.any_success is True

    def test_any_success_true_when_target_success(self):
        from src.phases.phase_3_synthesize import SynthesizeResult, STATUS_SUCCESS
        r = SynthesizeResult(target_doc_status=STATUS_SUCCESS)
        assert r.any_success is True


# ===========================================================================
# 2. 리서치 요약 포맷
# ===========================================================================

class TestResearchFormatter:
    def test_empty_research_returns_placeholder(self):
        from src.phases.phase_3_synthesize import _format_research_for_prompt
        result = _format_research_for_prompt({})
        assert "리서치 결과 없음" in result

    def test_successful_claims_included(self):
        from src.phases.phase_3_synthesize import _format_research_for_prompt
        data = _sample_parallel_research()
        result = _format_research_for_prompt(data)

        assert "작성 방법론" in result
        assert "시장 조사" in result
        assert "사업계획서 핵심 요소" in result
        assert "2026 시장 규모" in result

    def test_failed_adapters_excluded(self):
        """failed 상태의 어댑터 claims는 포함되지 않음."""
        from src.phases.phase_3_synthesize import _format_research_for_prompt
        data = {
            "subtopic A": {
                "gemini": {
                    "status": "success",
                    "claims": [{"text": "성공 내용", "source": "src"}],
                },
                "gpt": {
                    "status": "failed",
                    "claims": None,
                    "error": "timeout",
                },
            }
        }
        result = _format_research_for_prompt(data)
        assert "성공 내용" in result
        assert "timeout" not in result

    def test_adapter_name_appears(self):
        from src.phases.phase_3_synthesize import _format_research_for_prompt
        data = _sample_parallel_research()
        result = _format_research_for_prompt(data)
        # adapter 이름이 각 줄에 표기됨
        assert "gemini" in result
        assert "gpt" in result


# ===========================================================================
# 3. 정상 경로
# ===========================================================================

class TestHappyPath:
    def test_both_documents_succeed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        # 2번 호출되므로 side_effect로 다른 응답
        responses = [
            "# 기반정보 문서\n사업계획서 일반론...",
            "# 목표 산출물\n우리 앱의 사업계획서...",
        ]

        with patch(_CALL_LLM_PATCH, side_effect=responses):
            from src.phases.phase_3_synthesize import (
                synthesize_documents, STATUS_SUCCESS
            )
            result = synthesize_documents(
                "사업계획서 써줘",
                _sample_parallel_research(),
            )

            assert result.base_info_status == STATUS_SUCCESS
            assert result.target_doc_status == STATUS_SUCCESS
            assert result.base_info_doc is not None
            assert result.target_doc is not None
            assert "기반정보" in result.base_info_doc["document"]
            assert "목표 산출물" in result.target_doc["document"]
            assert result.error is None

    def test_documents_have_created_at(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_PATCH, side_effect=["doc a", "doc b"]):
            from src.phases.phase_3_synthesize import synthesize_documents
            result = synthesize_documents("요청", _sample_parallel_research())
            assert "created_at" in result.base_info_doc
            assert "created_at" in result.target_doc

    def test_any_success_true_when_both_succeed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_PATCH, side_effect=["doc a", "doc b"]):
            from src.phases.phase_3_synthesize import synthesize_documents
            result = synthesize_documents("요청", _sample_parallel_research())
            assert result.any_success is True


# ===========================================================================
# 4. 독립 실패 (한쪽만 실패)
# ===========================================================================

class TestIndependentFailure:
    def test_3a_fails_3b_succeeds(self, monkeypatch):
        """3a는 실패하지만 3b는 성공 — 독립 실행."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        # 첫 호출 None(=실패), 두 번째 성공
        with patch(_CALL_LLM_PATCH, side_effect=[None, "3b 성공 문서"]):
            from src.phases.phase_3_synthesize import (
                synthesize_documents, STATUS_FAILED, STATUS_SUCCESS
            )
            result = synthesize_documents("요청", _sample_parallel_research())

            assert result.base_info_status == STATUS_FAILED
            assert result.target_doc_status == STATUS_SUCCESS
            assert result.base_info_doc is None
            assert result.target_doc is not None
            assert result.error is not None
            assert "3a" in result.error

    def test_3b_fails_3a_succeeds(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        # 첫 호출 성공, 두 번째 None(=실패)
        with patch(_CALL_LLM_PATCH, side_effect=["3a 성공 문서", None]):
            from src.phases.phase_3_synthesize import (
                synthesize_documents, STATUS_FAILED, STATUS_SUCCESS
            )
            result = synthesize_documents("요청", _sample_parallel_research())

            assert result.base_info_status == STATUS_SUCCESS
            assert result.target_doc_status == STATUS_FAILED
            assert result.error is not None
            assert "3b" in result.error


# ===========================================================================
# 5. 둘 다 실패
# ===========================================================================

class TestBothFail:
    def test_both_fail_errors_merged(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_PATCH, return_value=None):
            from src.phases.phase_3_synthesize import (
                synthesize_documents, STATUS_FAILED
            )
            result = synthesize_documents("요청", _sample_parallel_research())

            assert result.base_info_status == STATUS_FAILED
            assert result.target_doc_status == STATUS_FAILED
            assert result.any_success is False
            assert result.error is not None
            assert "3a" in result.error
            assert "3b" in result.error


# ===========================================================================
# 6. 입력 검증
# ===========================================================================

class TestInputValidation:
    def test_empty_raw_input(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        from src.phases.phase_3_synthesize import synthesize_documents
        result = synthesize_documents("", _sample_parallel_research())
        assert result.error is not None
        assert "raw_input" in result.error

    def test_whitespace_only_raw_input(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        from src.phases.phase_3_synthesize import synthesize_documents
        result = synthesize_documents("   \n  ", _sample_parallel_research())
        assert result.error is not None

    def test_empty_parallel_research(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        from src.phases.phase_3_synthesize import synthesize_documents
        result = synthesize_documents("요청", {})
        assert result.error is not None
        assert "parallel_research" in result.error

    def test_no_successful_research(self, monkeypatch):
        """리서치 결과에 success가 하나도 없으면 합성 안 함."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        all_failed = {
            "subtopic A": {
                "gemini": {"status": "failed", "claims": None, "error": "x"},
                "gpt": {"status": "failed", "claims": None, "error": "y"},
            }
        }
        from src.phases.phase_3_synthesize import synthesize_documents
        result = synthesize_documents("요청", all_failed)
        assert result.error is not None
        assert "성공한 리서치" in result.error


# ===========================================================================
# 7. API 키 없음
# ===========================================================================

class TestNoApiKey:
    def test_no_key_both_fail(self, monkeypatch):
        """API 키 없으면 call_llm이 None 반환 → 둘 다 실패."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        # 실제 llm_utils.call_llm이 None 반환하는 동작을 그대로 사용
        # (환경변수가 없으면 API 호출 시도 없이 None 반환)
        from src.phases.phase_3_synthesize import (
            synthesize_documents, STATUS_FAILED
        )
        result = synthesize_documents("요청", _sample_parallel_research())
        assert result.base_info_status == STATUS_FAILED
        assert result.target_doc_status == STATUS_FAILED
        assert result.error is not None


# ===========================================================================
# 8. 마크다운 래퍼 제거
# ===========================================================================

class TestMarkdownUnwrap:
    def test_markdown_code_block_stripped(self, monkeypatch):
        """call_llm은 이미 clean_markdown_wrapper를 거친 결과를 반환.
        Phase 3는 그 결과를 신뢰하고 저장 — 저장된 문서가 ``` 로 시작하지 않아야 함."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        # call_llm이 wrapper 제거 후 반환하는 값을 모사
        cleaned = "# 제목\n본문"
        with patch(_CALL_LLM_PATCH, side_effect=[cleaned, cleaned]):
            from src.phases.phase_3_synthesize import synthesize_documents
            result = synthesize_documents("요청", _sample_parallel_research())
            assert not result.base_info_doc["document"].startswith("```")
            assert "# 제목" in result.base_info_doc["document"]

    def test_plain_code_block_stripped(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        cleaned = "문서 내용"
        with patch(_CALL_LLM_PATCH, side_effect=[cleaned, cleaned]):
            from src.phases.phase_3_synthesize import synthesize_documents
            result = synthesize_documents("요청", _sample_parallel_research())
            assert not result.base_info_doc["document"].startswith("```")

    def test_empty_response_treated_as_failure(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        # 빈 문자열 응답 → Phase 3가 failure로 처리
        with patch(_CALL_LLM_PATCH, side_effect=["", ""]):
            from src.phases.phase_3_synthesize import (
                synthesize_documents, STATUS_FAILED
            )
            result = synthesize_documents("요청", _sample_parallel_research())
            assert result.base_info_status == STATUS_FAILED
            assert result.target_doc_status == STATUS_FAILED


# ===========================================================================
# 9. 프롬프트 검증
# ===========================================================================

class TestPromptContent:
    def test_3a_prompt_includes_research(self, monkeypatch):
        """3a 프롬프트에 리서치 요약이 포함됨."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        captured = []
        def capture_call(prompt, *args, **kwargs):
            captured.append(prompt)
            return "doc"

        with patch(_CALL_LLM_PATCH, side_effect=capture_call):
            from src.phases.phase_3_synthesize import synthesize_documents
            synthesize_documents("요청", _sample_parallel_research())

        # 3a 프롬프트 (첫 호출)에 리서치 핵심 내용 있음
        assert len(captured) >= 1
        assert "사업계획서 핵심 요소" in captured[0]

    def test_3b_prompt_includes_raw_input(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        captured = []
        def capture_call(prompt, *args, **kwargs):
            captured.append(prompt)
            return "doc"

        with patch(_CALL_LLM_PATCH, side_effect=capture_call):
            from src.phases.phase_3_synthesize import synthesize_documents
            synthesize_documents("특별한_사용자_요청_문자열", _sample_parallel_research())

        # 3b 프롬프트 (두 번째 호출)에 사용자 원본 요청이 포함
        assert len(captured) >= 2
        assert "특별한_사용자_요청_문자열" in captured[1]


# ===========================================================================
# 10. 스모크 테스트
# ===========================================================================

class TestSmoke:
    def test_always_returns_synthesize_result(self, monkeypatch):
        """어떤 입력에도 SynthesizeResult 반환 (예외 전파 없음)."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        from src.phases.phase_3_synthesize import synthesize_documents, SynthesizeResult

        cases = [
            ("", {}),
            ("요청", {}),
            ("", _sample_parallel_research()),
            ("요청", _sample_parallel_research()),
        ]
        for raw_input, research in cases:
            result = synthesize_documents(raw_input, research)
            assert isinstance(result, SynthesizeResult)
