"""
Day 139 — OpenAI GPT-5.4 + web_search 어댑터 테스트 (Phase 2 단계 2)

테스트 포인트:
  1. is_available — OPENAI_API_KEY 체크
  2. skipped when no key
  3. Responses API 페이로드 검증
  4. 정상 응답 파싱 (message + annotations)
  5. 상태 처리 (completed/failed/in_progress)
  6. output 배열에서 message 추출
  7. annotations → citations 변환
  8. 비용 계산 (input_tokens/output_tokens)
  9. HTTP 에러 처리
  10. 모델 환경변수 오버라이드
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.research_v2.openai_adapter import (
    OpenAIResearchAdapter,
    _extract_message_content,
    _parse_annotations,
    _calculate_cost,
)
from src.research_v2 import STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED


_HTTPX_PATCH = "src.research_v2.openai_adapter.httpx.post"


def _build_message_output(text="리서치 보고서", annotations=None):
    """Responses API의 output 배열 중 message 항목 생성."""
    content_item = {
        "type": "output_text",
        "text": text,
    }
    if annotations is not None:
        content_item["annotations"] = annotations
    return {
        "type": "message",
        "role": "assistant",
        "content": [content_item],
    }


def _mock_success(text="응답", annotations=None, usage=None, extra_outputs=None):
    """정상 Responses API 응답."""
    r = MagicMock()
    r.status_code = 200
    output = list(extra_outputs or [])
    output.append(_build_message_output(text, annotations))
    body = {
        "id": "resp_abc123",
        "status": "completed",
        "output": output,
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


# ===========================================================================
# 1. is_available
# ===========================================================================

class TestAvailability:
    def test_no_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert OpenAIResearchAdapter().is_available() is False

    def test_with_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert OpenAIResearchAdapter().is_available() is True

    def test_empty_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "")
        assert OpenAIResearchAdapter().is_available() is False

    def test_whitespace_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "   ")
        assert OpenAIResearchAdapter().is_available() is False


# ===========================================================================
# 2. 키 없으면 skipped
# ===========================================================================

class TestSkippedWhenNoKey:
    def test_skipped(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = OpenAIResearchAdapter().research("q")
        assert result.status == STATUS_SKIPPED
        assert result.adapter_name == "openai_gpt_research"


# ===========================================================================
# 3. Responses API 페이로드
# ===========================================================================

class TestRequestPayload:
    def test_payload_structure(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-abc")
        adapter = OpenAIResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return _mock_success(text="ok")

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("질문입니다", timeout=60)

        assert captured["url"] == "https://api.openai.com/v1/responses"
        assert captured["headers"]["Authorization"] == "Bearer sk-abc"
        assert captured["headers"]["Content-Type"] == "application/json"
        assert captured["timeout"] == 60

        payload = captured["json"]
        assert payload["model"] == "gpt-5.4"
        assert isinstance(payload["input"], list)
        assert len(payload["input"]) == 2
        assert payload["input"][0]["role"] == "developer"
        assert payload["input"][1]["role"] == "user"
        assert payload["input"][1]["content"][0]["text"] == "질문입니다"
        assert {"type": "web_search_preview"} in payload["tools"]

    def test_env_override_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("OPENAI_RESEARCH_MODEL", "o4-mini")
        adapter = OpenAIResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success(text="ok")

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("q")

        assert captured["json"]["model"] == "o4-mini"

    def test_blank_env_model_uses_default(self, monkeypatch):
        """OPENAI_RESEARCH_MODEL이 공백이면 기본값."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("OPENAI_RESEARCH_MODEL", "   ")
        adapter = OpenAIResearchAdapter()

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success(text="ok")

        with patch(_HTTPX_PATCH, side_effect=capture):
            adapter.research("q")

        assert captured["json"]["model"] == "gpt-5.4"


# ===========================================================================
# 4. 정상 응답 파싱
# ===========================================================================

class TestSuccessfulParsing:
    def test_basic_success(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_success(
            text="# 보고서\n\n내용",
            annotations=[
                {"type": "url_citation", "url": "https://a.com", "title": "A"},
                {"type": "url_citation", "url": "https://b.com", "title": "B"},
            ],
            usage={"input_tokens": 100, "output_tokens": 2000},
        )):
            result = adapter.research("질문")

        assert result.status == STATUS_SUCCESS
        assert "보고서" in result.report
        assert len(result.citations) == 2
        assert result.citations[0].url == "https://a.com"
        assert result.model == "gpt-5.4"
        assert result.cost_usd > 0
        assert result.raw_meta.get("response_id") == "resp_abc123"

    def test_no_annotations_still_success(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_success(text="report")):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.citations == []

    def test_web_search_calls_ignored(self, monkeypatch):
        """output에 web_search_call 항목이 섞여있어도 message만 추출."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter()

        extra = [
            {"type": "web_search_call", "status": "completed"},
            {"type": "web_search_call", "status": "completed"},
        ]
        with patch(_HTTPX_PATCH, return_value=_mock_success(
            text="final report", extra_outputs=extra
        )):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.report == "final report"


# ===========================================================================
# 5. 상태 처리
# ===========================================================================

class TestResponseStatus:
    def test_failed_status(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "r",
            "status": "failed",
            "output": [],
        }
        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "failed" in (result.error or "")

    def test_cancelled_status(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "r",
            "status": "cancelled",
            "output": [],
        }
        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED


# ===========================================================================
# 6. _extract_message_content
# ===========================================================================

class TestExtractMessageContent:
    def test_single_message(self):
        output = [_build_message_output("hello", [])]
        text, citations = _extract_message_content(output)
        assert text == "hello"
        assert citations == []

    def test_multiple_messages_last_wins(self):
        """여러 message가 있으면 마지막 것."""
        output = [
            _build_message_output("first", []),
            _build_message_output("second", []),
        ]
        text, _ = _extract_message_content(output)
        assert text == "second"

    def test_no_message_returns_empty(self):
        output = [{"type": "web_search_call"}, {"type": "reasoning"}]
        text, citations = _extract_message_content(output)
        assert text == ""
        assert citations == []

    def test_none_input(self):
        assert _extract_message_content(None) == ("", [])

    def test_non_list_input(self):
        assert _extract_message_content("not a list") == ("", [])

    def test_malformed_content(self):
        """content 배열이 비어있거나 구조 이상."""
        output = [{"type": "message", "content": []}]
        text, _ = _extract_message_content(output)
        assert text == ""

    def test_missing_content_field(self):
        output = [{"type": "message"}]
        text, _ = _extract_message_content(output)
        assert text == ""


# ===========================================================================
# 7. _parse_annotations
# ===========================================================================

class TestParseAnnotations:
    def test_url_citations(self):
        result = _parse_annotations([
            {"type": "url_citation", "url": "https://a", "title": "A"},
            {"type": "url_citation", "url": "https://b"},
        ])
        assert len(result) == 2
        assert result[0].title == "A"
        assert result[1].title == ""

    def test_non_url_citation_skipped(self):
        """url_citation 외의 annotation type은 제외."""
        result = _parse_annotations([
            {"type": "url_citation", "url": "https://a"},
            {"type": "file_citation", "file_id": "f_123"},
            {"type": "code_output"},
        ])
        assert len(result) == 1

    def test_empty_url_skipped(self):
        result = _parse_annotations([
            {"type": "url_citation", "url": ""},
            {"type": "url_citation", "url": "https://valid"},
        ])
        assert len(result) == 1

    def test_none_input(self):
        assert _parse_annotations(None) == []

    def test_non_list_input(self):
        assert _parse_annotations("x") == []
        assert _parse_annotations(42) == []

    def test_non_dict_items_skipped(self):
        result = _parse_annotations([
            "not a dict",
            None,
            {"type": "url_citation", "url": "https://a"},
        ])
        assert len(result) == 1


# ===========================================================================
# 8. 비용 계산
# ===========================================================================

class TestCalculateCost:
    def test_basic_formula(self):
        """gpt-5.4: $2.50/$15.00 per 1M."""
        cost = _calculate_cost({"input_tokens": 1000, "output_tokens": 2000})
        # (1000×2.50 + 2000×15) / 1M = 0.0025 + 0.030 = 0.0325
        assert cost == pytest.approx(0.0325, abs=1e-6)

    def test_zero_usage(self):
        assert _calculate_cost({}) == 0.0
        assert _calculate_cost(None) == 0.0

    def test_non_dict_usage(self):
        assert _calculate_cost("not dict") == 0.0
        assert _calculate_cost([]) == 0.0

    def test_negative_tokens_clamped(self):
        assert _calculate_cost({"input_tokens": -100, "output_tokens": -50}) == 0.0

    def test_none_values(self):
        assert _calculate_cost({"input_tokens": None, "output_tokens": None}) == 0.0

    def test_string_tokens_coerced(self):
        cost = _calculate_cost({"input_tokens": "1000", "output_tokens": "500"})
        expected = (1000 * 2.5 + 500 * 15) / 1_000_000.0
        assert cost == pytest.approx(expected)

    def test_prompt_tokens_field_ignored(self):
        """OpenAI는 input_tokens/output_tokens를 씀. prompt_tokens는 무시됨."""
        cost = _calculate_cost({"prompt_tokens": 1000, "completion_tokens": 1000})
        assert cost == 0.0  # 올바른 필드명 아니라 0


# ===========================================================================
# 9. HTTP 에러
# ===========================================================================

class TestHTTPErrors:
    def test_401_unauthorized(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "bad")
        adapter = OpenAIResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_error(401, "Unauthorized")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "401" in (result.error or "")

    def test_500_server_error(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter()

        with patch(_HTTPX_PATCH, return_value=_mock_error(500)):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED

    def test_network_exception(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter()
        import httpx

        with patch(_HTTPX_PATCH, side_effect=httpx.ConnectError("refused")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "ConnectError" in (result.error or "")

    def test_timeout_exception(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter()
        import httpx

        with patch(_HTTPX_PATCH, side_effect=httpx.ReadTimeout("slow")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "Timeout" in (result.error or "")


# ===========================================================================
# 10. 실사용 시나리오
# ===========================================================================

class TestRealisticScenario:
    def test_full_openai_research_response(self, monkeypatch):
        """실제 OpenAI Responses API 응답 형태 시뮬레이션."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
        adapter = OpenAIResearchAdapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "resp_abc123xyz",
            "status": "completed",
            "output": [
                {"type": "web_search_call", "status": "completed"},
                {"type": "web_search_call", "status": "completed"},
                {"type": "web_search_call", "status": "completed"},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": """# Advanced Coffee Roasting Guide

## Key Stages
1. Drying phase (150-180°C)
2. Maillard reaction
3. First crack

## References
See citations.
""",
                            "annotations": [
                                {"type": "url_citation", "url": "https://scaa.org/roasting",
                                 "title": "SCAA Roasting", "start_index": 50, "end_index": 100},
                                {"type": "url_citation", "url": "https://sweetmarias.com",
                                 "title": "Sweet Maria's"},
                                {"type": "url_citation", "url": "https://coffee-review.com",
                                 "title": "Coffee Review"},
                            ],
                        },
                    ],
                },
            ],
            "usage": {
                "input_tokens": 200,
                "output_tokens": 3000,
                "total_tokens": 3200,
            },
        }

        with patch(_HTTPX_PATCH, return_value=mock_resp):
            result = adapter.research("커피 로스팅 심화 가이드")

        assert result.is_success
        assert "Coffee Roasting" in result.report
        assert len(result.citations) == 3
        assert result.citations[2].url == "https://coffee-review.com"
        assert result.model == "gpt-5.4"
        # 200×2.5/1M + 3000×15/1M = 0.0005 + 0.045 = 0.0455
        assert result.cost_usd == pytest.approx(0.0455, abs=1e-4)
        assert result.raw_meta["response_id"] == "resp_abc123xyz"
