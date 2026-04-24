"""
Day 141 — Anthropic Claude + web_search 어댑터 테스트 (Phase 2 단계 2)

테스트 포인트:
  1. is_available — ANTHROPIC_API_KEY 체크
  2. skipped when no key
  3. 페이로드 구조 (messages + tools + system)
  4. 정상 응답 파싱 (content 배열 혼합)
  5. text 블록 이어붙이기
  6. web_search_tool_result 에서 citations 추출
  7. 중복 URL 제거
  8. stop_reason / error 처리
  9. 비용 계산 (input_tokens / output_tokens)
  10. HTTP 에러
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.research_v2.claude_adapter import (
    ClaudeResearchAdapter,
    _extract_text_blocks,
    _extract_web_search_citations,
    _calculate_cost,
)
from src.research_v2 import STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED


_HTTPX_PATCH = "src.research_v2.claude_adapter.httpx.post"


def _mock_success(content=None, usage=None, stop_reason="end_turn"):
    """정상 Messages API 응답."""
    r = MagicMock()
    r.status_code = 200
    body = {
        "id": "msg_abc123",
        "type": "message",
        "role": "assistant",
        "content": content or [{"type": "text", "text": "응답"}],
        "stop_reason": stop_reason,
        "model": "claude-sonnet-4-6",
    }
    if usage is not None:
        body["usage"] = usage
    r.json.return_value = body
    return r


def _mock_error(status=500, text="Internal"):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


def _text_block(text):
    return {"type": "text", "text": text}


def _search_tool_use_block(query="query"):
    return {
        "type": "server_tool_use",
        "id": "tu_123",
        "name": "web_search",
        "input": {"query": query},
    }


def _search_result_block(results):
    """results: list of {url, title, snippet?}"""
    return {
        "type": "web_search_tool_result",
        "tool_use_id": "tu_123",
        "content": [
            {
                "type": "web_search_result",
                "url": r["url"],
                "title": r.get("title", ""),
                "snippet": r.get("snippet", ""),
                "encrypted_content": "encrypted_placeholder",
            }
            for r in results
        ],
    }


# ===========================================================================
# 1. is_available
# ===========================================================================

class TestAvailability:
    def test_no_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert ClaudeResearchAdapter().is_available() is False

    def test_with_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxx")
        assert ClaudeResearchAdapter().is_available() is True

    def test_empty_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        assert ClaudeResearchAdapter().is_available() is False

    def test_whitespace_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
        assert ClaudeResearchAdapter().is_available() is False


# ===========================================================================
# 2. Skipped when no key
# ===========================================================================

class TestSkippedWhenNoKey:
    def test_skipped(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = ClaudeResearchAdapter().research("q")
        assert result.status == STATUS_SKIPPED
        assert result.adapter_name == "claude_web_research"


# ===========================================================================
# 3. 페이로드
# ===========================================================================

class TestRequestPayload:
    def test_endpoint_and_headers(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abc")
        adapter = ClaudeResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return _mock_success()

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("질문", timeout=60)

        assert captured["url"] == "https://api.anthropic.com/v1/messages"
        assert captured["headers"]["x-api-key"] == "sk-ant-abc"
        assert captured["headers"]["anthropic-version"] == "2023-06-01"
        assert captured["timeout"] == 60

    def test_payload_includes_web_search_tool(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success()

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("q")

        tools = captured["json"]["tools"]
        assert len(tools) == 1
        assert tools[0]["type"] == "web_search_20250305"
        assert tools[0]["name"] == "web_search"

    def test_user_message_included(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success()

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("구체적인 질문")

        messages = captured["json"]["messages"]
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "구체적인 질문"

    def test_system_prompt_included(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success()

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("q")

        sys = captured["json"]["system"]
        assert isinstance(sys, str)
        assert "research assistant" in sys.lower()

    def test_env_override_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.setenv("CLAUDE_RESEARCH_MODEL", "claude-opus-4-7")
        adapter = ClaudeResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success()

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("q")

        assert captured["json"]["model"] == "claude-opus-4-7"


# ===========================================================================
# 4. 정상 응답 파싱
# ===========================================================================

class TestSuccessfulParsing:
    def test_basic_success(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()

        content = [
            _text_block("# 보고서\n\n내용입니다."),
        ]
        with patch(_HTTPX_PATCH, return_value=_mock_success(
            content=content,
            usage={"input_tokens": 100, "output_tokens": 2000},
        )):
            result = adapter.research("질문")

        assert result.status == STATUS_SUCCESS
        assert "보고서" in result.report
        assert result.model == "claude-sonnet-4-6"
        assert result.cost_usd > 0
        assert result.raw_meta.get("message_id") == "msg_abc123"

    def test_with_web_search_citations(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()

        content = [
            _text_block("검색을 시작합니다."),
            _search_tool_use_block("coffee roasting"),
            _search_result_block([
                {"url": "https://scaa.org", "title": "SCAA"},
                {"url": "https://sweet.com", "title": "Sweet Maria's"},
            ]),
            _text_block("# 커피 로스팅 보고서\n\n상세 내용..."),
        ]
        with patch(_HTTPX_PATCH, return_value=_mock_success(content=content)):
            result = adapter.research("커피 로스팅")

        assert result.status == STATUS_SUCCESS
        assert "커피 로스팅 보고서" in result.report
        assert "검색을 시작합니다" in result.report
        assert len(result.citations) == 2
        assert result.citations[0].url == "https://scaa.org"

    def test_multiple_text_blocks_joined(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()

        content = [
            _text_block("Part 1"),
            _search_tool_use_block(),
            _search_result_block([{"url": "https://a.com"}]),
            _text_block("Part 2"),
            _search_tool_use_block("second search"),
            _search_result_block([{"url": "https://b.com"}]),
            _text_block("Part 3"),
        ]
        with patch(_HTTPX_PATCH, return_value=_mock_success(content=content)):
            result = adapter.research("q")

        assert "Part 1" in result.report
        assert "Part 2" in result.report
        assert "Part 3" in result.report
        assert len(result.citations) == 2


# ===========================================================================
# 5. _extract_text_blocks
# ===========================================================================

class TestExtractTextBlocks:
    def test_single_text(self):
        content = [_text_block("hello")]
        assert _extract_text_blocks(content) == "hello"

    def test_multiple_texts_joined(self):
        content = [_text_block("a"), _text_block("b"), _text_block("c")]
        assert _extract_text_blocks(content) == "a\n\nb\n\nc"

    def test_non_text_blocks_ignored(self):
        content = [
            _text_block("visible"),
            _search_tool_use_block(),
            _search_result_block([{"url": "https://x"}]),
        ]
        assert _extract_text_blocks(content) == "visible"

    def test_empty_content(self):
        assert _extract_text_blocks([]) == ""

    def test_none_content(self):
        assert _extract_text_blocks(None) == ""

    def test_non_list_content(self):
        assert _extract_text_blocks("not a list") == ""

    def test_empty_text_skipped(self):
        content = [_text_block(""), _text_block("valid"), _text_block("   ")]
        assert _extract_text_blocks(content) == "valid"

    def test_none_text_field(self):
        content = [{"type": "text", "text": None}, _text_block("valid")]
        assert _extract_text_blocks(content) == "valid"


# ===========================================================================
# 6. _extract_web_search_citations
# ===========================================================================

class TestExtractCitations:
    def test_single_search_result_block(self):
        content = [
            _search_result_block([
                {"url": "https://a.com", "title": "A"},
                {"url": "https://b.com", "title": "B", "snippet": "desc"},
            ])
        ]
        result = _extract_web_search_citations(content)
        assert len(result) == 2
        assert result[0].title == "A"
        assert result[1].snippet == "desc"

    def test_multiple_search_result_blocks(self):
        content = [
            _search_result_block([{"url": "https://a.com"}]),
            _text_block("middle"),
            _search_result_block([{"url": "https://b.com"}]),
        ]
        result = _extract_web_search_citations(content)
        assert len(result) == 2

    def test_duplicate_urls_deduplicated(self):
        content = [
            _search_result_block([
                {"url": "https://a.com", "title": "A1"},
                {"url": "https://b.com"},
            ]),
            _search_result_block([
                {"url": "https://a.com", "title": "A2"},  # 중복
                {"url": "https://c.com"},
            ]),
        ]
        result = _extract_web_search_citations(content)
        assert len(result) == 3
        # 첫 번째가 유지됨
        urls = [c.url for c in result]
        assert urls.count("https://a.com") == 1

    def test_empty_url_skipped(self):
        content = [
            _search_result_block([
                {"url": "", "title": "empty"},
                {"url": "https://valid.com"},
            ])
        ]
        result = _extract_web_search_citations(content)
        assert len(result) == 1

    def test_no_search_blocks(self):
        content = [_text_block("only text")]
        assert _extract_web_search_citations(content) == []

    def test_none_content(self):
        assert _extract_web_search_citations(None) == []

    def test_non_list(self):
        assert _extract_web_search_citations("x") == []

    def test_search_block_without_content_field(self):
        content = [{"type": "web_search_tool_result"}]  # content 없음
        assert _extract_web_search_citations(content) == []


# ===========================================================================
# 7. 에러 / stop_reason
# ===========================================================================

class TestErrorHandling:
    def test_error_type_response(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "type": "error",
            "error": {"type": "rate_limit_error", "message": "Rate limit"},
        }
        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "Rate limit" in (result.error or "")

    def test_no_content_field(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "msg_1"}
        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "no content" in (result.error or "")

    def test_empty_content_array(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"content": []}
        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED

    def test_only_tool_use_blocks_no_text(self, monkeypatch):
        """text 블록 없이 tool_use만 있으면 empty report."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()

        content = [_search_tool_use_block(), _search_result_block([])]
        with patch(_HTTPX_PATCH, return_value=_mock_success(
            content=content, stop_reason="max_tokens"
        )):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "max_tokens" in (result.error or "")


# ===========================================================================
# 8. 비용 계산
# ===========================================================================

class TestCalculateCost:
    def test_basic_formula_sonnet(self):
        """Sonnet 4.6: $3/$15 per 1M."""
        cost = _calculate_cost({"input_tokens": 1000, "output_tokens": 2000})
        # (1000×3 + 2000×15) / 1M = 0.003 + 0.030 = 0.033
        assert cost == pytest.approx(0.033, abs=1e-6)

    def test_zero_usage(self):
        assert _calculate_cost({}) == 0.0
        assert _calculate_cost(None) == 0.0

    def test_non_dict(self):
        assert _calculate_cost("x") == 0.0

    def test_negative_clamped(self):
        assert _calculate_cost({
            "input_tokens": -100, "output_tokens": -50,
        }) == 0.0

    def test_none_values(self):
        assert _calculate_cost({
            "input_tokens": None, "output_tokens": None,
        }) == 0.0

    def test_string_coerced(self):
        cost = _calculate_cost({
            "input_tokens": "1000", "output_tokens": "500",
        })
        expected = (1000 * 3 + 500 * 15) / 1_000_000.0
        assert cost == pytest.approx(expected)


# ===========================================================================
# 9. HTTP 에러
# ===========================================================================

class TestHTTPErrors:
    def test_401_unauthorized(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "bad")
        adapter = ClaudeResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_error(401, "Unauthorized")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "401" in (result.error or "")

    def test_429_rate_limit(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_error(429, "Rate limit")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED

    def test_500_error(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_error(500)):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED

    def test_network_exception(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        adapter = ClaudeResearchAdapter()
        import httpx

        with patch(_HTTPX_PATCH, side_effect=httpx.ConnectError("refused")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "ConnectError" in (result.error or "")


# ===========================================================================
# 10. 실사용 시나리오
# ===========================================================================

class TestRealisticScenario:
    def test_full_claude_research_response(self, monkeypatch):
        """실제 Claude Messages API 응답 형태."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
        adapter = ClaudeResearchAdapter()

        content = [
            _text_block("먼저 커피 로스팅에 대해 검색해보겠습니다."),
            _search_tool_use_block("coffee roasting stages"),
            _search_result_block([
                {"url": "https://scaa.org/roasting", "title": "SCAA"},
                {"url": "https://sweetmarias.com", "title": "Sweet Maria's"},
            ]),
            _text_block("추가 정보를 찾아보겠습니다."),
            _search_tool_use_block("Maillard reaction coffee"),
            _search_result_block([
                {"url": "https://coffeeresearch.org/chemistry", "title": "Coffee Research"},
                # 중복으로 들어와도 제거됨
                {"url": "https://scaa.org/roasting", "title": "SCAA"},
            ]),
            _text_block("""# Coffee Roasting — Comprehensive Guide

## Stages
1. **Drying phase** (150-180°C)
2. **Maillard reaction**
3. **First crack**
4. **Development**

## Key Chemistry
Maillard reaction creates hundreds of aromatic compounds.

## References
Multiple authoritative sources consulted.
"""),
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "msg_realistic",
            "type": "message",
            "role": "assistant",
            "content": content,
            "stop_reason": "end_turn",
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": 180,
                "output_tokens": 2800,
                "cache_read_input_tokens": 0,
            },
        }

        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("커피 로스팅 심화 가이드")

        assert result.is_success
        assert "Coffee Roasting" in result.report
        assert "먼저 커피 로스팅" in result.report  # 중간 텍스트도 포함
        # 중복 제거로 SCAA 한 번만
        assert len(result.citations) == 3
        urls = [c.url for c in result.citations]
        assert urls.count("https://scaa.org/roasting") == 1
        assert result.model == "claude-sonnet-4-6"
        # 180×3/1M + 2800×15/1M = 0.00054 + 0.042 = 0.04254
        assert result.cost_usd == pytest.approx(0.04254, abs=1e-4)
        assert result.raw_meta["stop_reason"] == "end_turn"
