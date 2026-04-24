"""
Day 132 — call_llm_json 단위 테스트 (Step 14-2)

테스트 포인트:
  1. _strip_json_fence 헬퍼 — 래퍼/공백/설명문 제거
  2. 정상 JSON 파싱
  3. 마크다운 래퍼 자동 제거
  4. 앞뒤 설명문 제거
  5. 파싱 실패 시 재시도 (보정 프롬프트 확인)
  6. 모든 재시도 실패 → None
  7. API 키 없음 → None
  8. 빈 응답 → None
  9. retry_limit=0 동작
  10. 하위호환: 기존 call_llm 변경 없음
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch

from src.utils.llm_utils import (
    call_llm,
    call_llm_json,
    clean_markdown_wrapper,
    _strip_json_fence,
)


_CALL_LLM_PATCH = "src.utils.llm_utils.call_llm"


# ===========================================================================
# 1. _strip_json_fence 헬퍼
# ===========================================================================

class TestStripJsonFence:
    def test_empty_input(self):
        assert _strip_json_fence("") == ""
        assert _strip_json_fence(None) == ""

    def test_pure_json_object_untouched(self):
        text = '{"key": "value"}'
        assert _strip_json_fence(text) == '{"key": "value"}'

    def test_pure_json_array_untouched(self):
        text = '[1, 2, 3]'
        assert _strip_json_fence(text) == '[1, 2, 3]'

    def test_json_code_block_stripped(self):
        text = '```json\n{"a": 1}\n```'
        assert _strip_json_fence(text) == '{"a": 1}'

    def test_plain_code_block_stripped(self):
        text = '```\n{"a": 1}\n```'
        assert _strip_json_fence(text) == '{"a": 1}'

    def test_leading_explanation_removed(self):
        text = '다음은 JSON 결과입니다:\n{"a": 1}'
        assert _strip_json_fence(text) == '{"a": 1}'

    def test_trailing_explanation_removed(self):
        text = '{"a": 1}\n위 결과를 참고하세요.'
        assert _strip_json_fence(text) == '{"a": 1}'

    def test_both_sides_stripped(self):
        text = '설명:\n```json\n{"x": [1, 2]}\n```\n끝.'
        assert _strip_json_fence(text) == '{"x": [1, 2]}'

    def test_non_json_text_returned_as_is(self):
        """JSON 시작 문자가 없으면 원본 반환."""
        text = "그냥 평범한 텍스트"
        assert _strip_json_fence(text) == "그냥 평범한 텍스트"


# ===========================================================================
# 2. 정상 파싱
# ===========================================================================

class TestSuccessfulParse:
    def test_valid_json_object(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_CALL_LLM_PATCH, return_value='{"a": 1, "b": "hello"}'):
            result = call_llm_json("prompt", "model", 30.0)
            assert result == {"a": 1, "b": "hello"}

    def test_valid_json_array(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_CALL_LLM_PATCH, return_value='[{"a": 1}, {"b": 2}]'):
            result = call_llm_json("prompt", "model", 30.0)
            assert result == [{"a": 1}, {"b": 2}]

    def test_nested_json(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_CALL_LLM_PATCH, return_value='{"nested": {"list": [1, 2, 3]}}'):
            result = call_llm_json("prompt", "model", 30.0)
            assert result == {"nested": {"list": [1, 2, 3]}}

    def test_korean_content_preserved(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_CALL_LLM_PATCH, return_value='{"name": "홍길동", "age": 30}'):
            result = call_llm_json("prompt", "model", 30.0)
            assert result["name"] == "홍길동"
            assert result["age"] == 30


# ===========================================================================
# 3. 마크다운 래퍼 자동 제거
# ===========================================================================

class TestMarkdownWrapperRemoval:
    def test_json_code_block(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        response = '```json\n{"status": "ok"}\n```'
        with patch(_CALL_LLM_PATCH, return_value=response):
            result = call_llm_json("prompt", "model", 30.0)
            assert result == {"status": "ok"}

    def test_plain_code_block(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        response = '```\n{"status": "ok"}\n```'
        with patch(_CALL_LLM_PATCH, return_value=response):
            result = call_llm_json("prompt", "model", 30.0)
            assert result == {"status": "ok"}


# ===========================================================================
# 4. 앞뒤 설명문 제거
# ===========================================================================

class TestExplanationStripping:
    def test_leading_explanation(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        response = '요청하신 결과입니다:\n{"verdict": "go"}'
        with patch(_CALL_LLM_PATCH, return_value=response):
            result = call_llm_json("prompt", "model", 30.0)
            assert result == {"verdict": "go"}

    def test_trailing_explanation(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        response = '{"verdict": "go"}\n\n위 결과 확인 바랍니다.'
        with patch(_CALL_LLM_PATCH, return_value=response):
            result = call_llm_json("prompt", "model", 30.0)
            assert result == {"verdict": "go"}


# ===========================================================================
# 5. 재시도 동작
# ===========================================================================

class TestRetryBehavior:
    def test_first_fail_second_succeed(self, monkeypatch):
        """첫 응답이 JSON 아님 → 재시도로 복구."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        responses = [
            "설명만 있고 JSON 없음",            # 1st: 실패
            '{"ok": true}',                      # 2nd: 성공
        ]
        with patch(_CALL_LLM_PATCH, side_effect=responses) as mock:
            result = call_llm_json("prompt", "model", 30.0)
            assert result == {"ok": True}
            assert mock.call_count == 2

    def test_second_prompt_contains_error_hint(self, monkeypatch):
        """재시도 시 보정 프롬프트에 '이전 응답' 문구 포함."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        responses = ["망가진 응답", '{"ok": true}']
        captured_prompts = []

        def capture(prompt, *args, **kwargs):
            captured_prompts.append(prompt)
            return responses[len(captured_prompts) - 1]

        with patch(_CALL_LLM_PATCH, side_effect=capture):
            call_llm_json("원본 프롬프트", "model", 30.0)

        assert len(captured_prompts) == 2
        assert "원본 프롬프트" in captured_prompts[0]
        assert "원본 프롬프트" in captured_prompts[1]
        assert "이전 응답" in captured_prompts[1]
        assert "JSON" in captured_prompts[1]

    def test_first_and_second_fail_third_succeed(self, monkeypatch):
        """기본 retry_limit=2 → 총 3회 시도."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        responses = ["망가짐1", "망가짐2", '{"ok": true}']
        with patch(_CALL_LLM_PATCH, side_effect=responses) as mock:
            result = call_llm_json("prompt", "model", 30.0)
            assert result == {"ok": True}
            assert mock.call_count == 3


# ===========================================================================
# 6. 모든 재시도 실패
# ===========================================================================

class TestAllRetriesFail:
    def test_all_three_attempts_fail(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        responses = ["망가짐1", "망가짐2", "망가짐3"]
        with patch(_CALL_LLM_PATCH, side_effect=responses) as mock:
            result = call_llm_json("prompt", "model", 30.0)
            assert result is None
            assert mock.call_count == 3

    def test_plain_text_response_fails(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        # JSON 없는 순수 텍스트
        with patch(_CALL_LLM_PATCH, return_value="그냥 설명 텍스트"):
            result = call_llm_json("prompt", "model", 30.0)
            assert result is None


# ===========================================================================
# 7. API 키 없음
# ===========================================================================

class TestNoApiKey:
    def test_no_key_returns_none(self, monkeypatch):
        """call_llm이 None 반환 → call_llm_json도 즉시 None."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with patch(_CALL_LLM_PATCH, return_value=None) as mock:
            result = call_llm_json("prompt", "model", 30.0)
            assert result is None
            # 재시도 의미 없음 — 1회만 호출
            assert mock.call_count == 1


# ===========================================================================
# 8. 빈 응답 처리
# ===========================================================================

class TestEmptyResponse:
    def test_empty_string_retries(self, monkeypatch):
        """빈 응답은 재시도 대상."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        responses = ["", '{"ok": true}']
        with patch(_CALL_LLM_PATCH, side_effect=responses) as mock:
            result = call_llm_json("prompt", "model", 30.0)
            assert result == {"ok": True}
            assert mock.call_count == 2

    def test_whitespace_only_retries(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        responses = ["   \n\n  ", '{"ok": true}']
        with patch(_CALL_LLM_PATCH, side_effect=responses):
            result = call_llm_json("prompt", "model", 30.0)
            assert result == {"ok": True}


# ===========================================================================
# 9. retry_limit 파라미터
# ===========================================================================

class TestRetryLimitParameter:
    def test_retry_limit_zero_one_attempt_only(self, monkeypatch):
        """retry_limit=0 → 재시도 없음 (총 1회)."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_CALL_LLM_PATCH, return_value="망가짐") as mock:
            result = call_llm_json("prompt", "model", 30.0, retry_limit=0)
            assert result is None
            assert mock.call_count == 1

    def test_retry_limit_one_two_attempts(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        responses = ["망가짐", "망가짐"]
        with patch(_CALL_LLM_PATCH, side_effect=responses) as mock:
            result = call_llm_json("prompt", "model", 30.0, retry_limit=1)
            assert result is None
            assert mock.call_count == 2

    def test_negative_retry_limit_treated_as_zero(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        with patch(_CALL_LLM_PATCH, return_value="망가짐") as mock:
            result = call_llm_json("prompt", "model", 30.0, retry_limit=-5)
            assert result is None
            assert mock.call_count == 1


# ===========================================================================
# 10. 하위호환 — 기존 call_llm 변경 없음
# ===========================================================================

class TestBackwardCompatibility:
    def test_call_llm_signature_unchanged(self, monkeypatch):
        """기존 call_llm(prompt, model, timeout) 그대로 동작."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        # call_llm 자체를 모킹하면 의미 없으니, httpx.post를 패치
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "결과 텍스트"}}]
        }

        with patch("src.utils.llm_utils.httpx.post", return_value=mock_response):
            result = call_llm("프롬프트", "model", 30.0)
            assert result == "결과 텍스트"

    def test_clean_markdown_wrapper_still_exported(self):
        """기존 import 경로 유지."""
        assert callable(clean_markdown_wrapper)
        assert clean_markdown_wrapper("```markdown\nhello\n```") == "hello"


# ===========================================================================
# 11. 실사용 시나리오
# ===========================================================================

class TestRealisticScenarios:
    def test_phase_1_subtopic_response(self, monkeypatch):
        """Phase 1이 받을 법한 응답 형태."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        response = '''```json
{
  "refined_query": "개인 카페 창업자를 위한 완전한 운영 가이드"
}
```'''
        with patch(_CALL_LLM_PATCH, return_value=response):
            result = call_llm_json("prompt", "model", 30.0)
            assert "refined_query" in result
            assert "카페" in result["refined_query"]

    def test_phase_4_audit_response(self, monkeypatch):
        """Phase 4 감사관이 받을 법한 응답 형태."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        response = '''{
  "verdict": "pass",
  "issues": [],
  "suggestions": ["더 구체적인 예시 추가 권장"]
}'''
        with patch(_CALL_LLM_PATCH, return_value=response):
            result = call_llm_json("prompt", "model", 30.0)
            assert result["verdict"] == "pass"
            assert isinstance(result["suggestions"], list)
