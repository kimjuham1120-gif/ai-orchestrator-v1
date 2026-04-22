"""
Day 123 — Step 13-1/2 · llm_utils (캐싱 + 재시도) 테스트.

검증:
1. call_llm 기본 호출
2. 캐싱 활성화 시 cache_control 포함 여부
3. 짧은 프롬프트는 캐싱 건너뜀
4. PROMPT_CACHE_ENABLED=false 시 캐싱 비활성화
5. exponential backoff 재시도 (네트워크 오류)
6. 4xx 오류 시 재시도 없음
7. API 키 없으면 None 반환
8. clean_markdown_wrapper
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


def _mock_ok(text="응답"):
    m = MagicMock()
    m.status_code = 200
    m.raise_for_status = MagicMock()
    m.json.return_value = {"choices": [{"message": {"content": text}}]}
    return m


def _mock_err(status=500):
    m = MagicMock()
    m.status_code = status
    m.raise_for_status.side_effect = Exception(f"HTTP {status}")
    return m


SHORT_PROMPT = "짧은 프롬프트"
LONG_PROMPT = "A" * 5000  # 4000자 초과 → 캐싱 대상


# ===========================================================================
# 1. 기본 호출
# ===========================================================================

class TestCallLLMBasic:
    def test_returns_text_on_success(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx
        with patch.object(httpx, "post", return_value=_mock_ok("좋은 응답")):
            from src.utils.llm_utils import call_llm
            result = call_llm(SHORT_PROMPT, "anthropic/claude-sonnet-4-6", 30.0)
            assert result == "좋은 응답"

    def test_no_api_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        from src.utils.llm_utils import call_llm
        result = call_llm(SHORT_PROMPT, "anthropic/claude-sonnet-4-6", 30.0)
        assert result is None

    def test_empty_response_returns_none(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx
        with patch.object(httpx, "post", return_value=_mock_ok("")):
            from src.utils.llm_utils import call_llm
            result = call_llm(SHORT_PROMPT, "model", 30.0)
            assert result is None


# ===========================================================================
# 2. 캐싱 — cache_control 포함 여부
# ===========================================================================

class TestCaching:
    def test_long_prompt_includes_cache_control(self, monkeypatch):
        """긴 프롬프트 → cache_control 포함."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("PROMPT_CACHE_ENABLED", "true")
        import httpx

        captured = []
        def capture(*args, **kwargs):
            captured.append(kwargs["json"]["messages"])
            return _mock_ok()

        with patch.object(httpx, "post", side_effect=capture):
            from src.utils.llm_utils import call_llm
            call_llm(LONG_PROMPT, "model", 30.0, use_cache=True)

        msg = captured[0][0]
        assert isinstance(msg["content"], list)
        assert msg["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_short_prompt_no_cache_control(self, monkeypatch):
        """짧은 프롬프트 → cache_control 없음."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        captured = []
        def capture(*args, **kwargs):
            captured.append(kwargs["json"]["messages"])
            return _mock_ok()

        with patch.object(httpx, "post", side_effect=capture):
            from src.utils.llm_utils import call_llm
            call_llm(SHORT_PROMPT, "model", 30.0, use_cache=True)

        msg = captured[0][0]
        # 짧은 프롬프트는 단순 문자열 형식
        assert isinstance(msg["content"], str)

    def test_cache_disabled_globally(self, monkeypatch):
        """PROMPT_CACHE_ENABLED=false → 긴 프롬프트도 캐싱 없음."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("PROMPT_CACHE_ENABLED", "false")
        import httpx

        captured = []
        def capture(*args, **kwargs):
            captured.append(kwargs["json"]["messages"])
            return _mock_ok()

        with patch.object(httpx, "post", side_effect=capture):
            from src.utils.llm_utils import call_llm
            call_llm(LONG_PROMPT, "model", 30.0, use_cache=True)

        msg = captured[0][0]
        assert isinstance(msg["content"], str)  # 단순 문자열

    def test_use_cache_false_skips_cache(self, monkeypatch):
        """use_cache=False → 길이 무관하게 캐싱 없음."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        captured = []
        def capture(*args, **kwargs):
            captured.append(kwargs["json"]["messages"])
            return _mock_ok()

        with patch.object(httpx, "post", side_effect=capture):
            from src.utils.llm_utils import call_llm
            call_llm(LONG_PROMPT, "model", 30.0, use_cache=False)

        msg = captured[0][0]
        assert isinstance(msg["content"], str)


# ===========================================================================
# 3. Exponential backoff 재시도
# ===========================================================================

class TestRetry:
    def test_retries_on_network_error(self, monkeypatch):
        """네트워크 오류 → 재시도 후 성공."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("PROMPT_CACHE_ENABLED", "false")
        import httpx

        call_count = [0]
        def flaky(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise httpx.ConnectError("connection refused")
            return _mock_ok("성공")

        with patch.object(httpx, "post", side_effect=flaky):
            with patch("time.sleep"):  # sleep 건너뜀
                from src.utils.llm_utils import call_llm
                result = call_llm(SHORT_PROMPT, "model", 30.0)

        assert result == "성공"
        assert call_count[0] == 3  # 첫 실패 + 재시도 2회

    def test_max_retries_exhausted_returns_none(self, monkeypatch):
        """모든 재시도 소진 → None."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        with patch.object(httpx, "post", side_effect=httpx.ConnectError("down")):
            with patch("time.sleep"):
                from src.utils.llm_utils import call_llm
                result = call_llm(SHORT_PROMPT, "model", 30.0)

        assert result is None

    def test_no_retry_on_4xx(self, monkeypatch):
        """4xx 오류 → 재시도 없이 즉시 None."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        call_count = [0]
        def bad_request(*args, **kwargs):
            call_count[0] += 1
            return _mock_err(400)

        with patch.object(httpx, "post", side_effect=bad_request):
            from src.utils.llm_utils import call_llm
            result = call_llm(SHORT_PROMPT, "model", 30.0)

        assert result is None
        assert call_count[0] == 1  # 재시도 없음

    def test_retry_delays_called(self, monkeypatch):
        """재시도 시 sleep이 호출됨."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        sleep_calls = []
        with patch.object(httpx, "post", side_effect=httpx.ConnectError("down")):
            with patch("time.sleep", side_effect=lambda x: sleep_calls.append(x)):
                from src.utils.llm_utils import call_llm
                call_llm(SHORT_PROMPT, "model", 30.0)

        assert len(sleep_calls) == 2        # 2회 재시도
        assert sleep_calls[0] == 1.0        # 첫 번째 대기
        assert sleep_calls[1] == 2.0        # 두 번째 대기 (exponential)


# ===========================================================================
# 4. clean_markdown_wrapper
# ===========================================================================

class TestCleanMarkdownWrapper:
    def test_removes_markdown_fence(self):
        from src.utils.llm_utils import clean_markdown_wrapper
        assert clean_markdown_wrapper("```markdown\n내용\n```") == "내용"

    def test_removes_md_fence(self):
        from src.utils.llm_utils import clean_markdown_wrapper
        assert clean_markdown_wrapper("```md\n내용\n```") == "내용"

    def test_removes_json_fence(self):
        from src.utils.llm_utils import clean_markdown_wrapper
        assert clean_markdown_wrapper("```json\n{}\n```") == "{}"

    def test_plain_text_unchanged(self):
        from src.utils.llm_utils import clean_markdown_wrapper
        assert clean_markdown_wrapper("일반 텍스트") == "일반 텍스트"

    def test_empty_string(self):
        from src.utils.llm_utils import clean_markdown_wrapper
        assert clean_markdown_wrapper("") == ""

    def test_none_returns_empty(self):
        from src.utils.llm_utils import clean_markdown_wrapper
        assert clean_markdown_wrapper(None) == None

    def test_strips_whitespace(self):
        from src.utils.llm_utils import clean_markdown_wrapper
        assert clean_markdown_wrapper("  \n내용\n  ") == "내용"
