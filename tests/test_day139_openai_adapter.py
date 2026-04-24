"""
Day 139 — OpenAI 어댑터 테스트 (듀얼 모드 - Step 1)

Step 1 범위:
  1. mode 파라미터 검증 (web_search / deep_research / invalid)
  2. 모드별 모델 / 타임아웃
  3. web_search 하위호환 (기존 38개 테스트 전부 통과)
  4. Deep Research 기본 성공 경로 (submit → poll → parse)
  5. 환경변수 오버라이드 (web + DR 각각)

Step 2 (추후):
  - 폴링 타임아웃
  - 중간 failed/cancelled
  - submit 실패
  - 폴링 중 네트워크 오류
  - 모드별 비용 상세

이 파일은 기존 테스트(38개)를 그대로 유지하고 새 테스트를 추가합니다.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.research_v2.openai_adapter import (
    OpenAIResearchAdapter,
    MODE_WEB_SEARCH,
    MODE_DEEP_RESEARCH,
    _MODE_CONFIG,
    _extract_message_content,
    _parse_annotations,
    _calculate_cost,
)
from src.research_v2 import STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED


_HTTPX_POST_PATCH = "src.research_v2.openai_adapter.httpx.post"
_HTTPX_GET_PATCH = "src.research_v2.openai_adapter.httpx.get"
_TIME_SLEEP_PATCH = "src.research_v2.openai_adapter.time.sleep"


# ===========================================================================
# 공통 mock 헬퍼
# ===========================================================================

def _build_message_output(text="리서치 보고서", annotations=None):
    content_item = {"type": "output_text", "text": text}
    if annotations is not None:
        content_item["annotations"] = annotations
    return {
        "type": "message",
        "role": "assistant",
        "content": [content_item],
    }


def _mock_success(text="응답", annotations=None, usage=None, extra_outputs=None,
                   response_id="resp_abc123", status="completed"):
    """완성된 응답 mock (web_search / DR 최종 공통)."""
    r = MagicMock()
    r.status_code = 200
    output = list(extra_outputs or [])
    output.append(_build_message_output(text, annotations))
    body = {
        "id": response_id,
        "status": status,
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


def _mock_queued(response_id="resp_new"):
    """Deep Research submit 응답 — queued 상태."""
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"id": response_id, "status": "queued"}
    return r


def _mock_polling_status(status="in_progress", response_id="resp_new"):
    """폴링 중간 상태."""
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"id": response_id, "status": status}
    return r


# ===========================================================================
# A. mode 파라미터 검증 (신규)
# ===========================================================================

class TestModeParameter:
    def test_default_mode_is_web_search(self):
        adapter = OpenAIResearchAdapter()
        assert adapter.mode == MODE_WEB_SEARCH

    def test_explicit_web_search(self):
        adapter = OpenAIResearchAdapter(mode="web_search")
        assert adapter.mode == "web_search"

    def test_explicit_deep_research(self):
        adapter = OpenAIResearchAdapter(mode="deep_research")
        assert adapter.mode == "deep_research"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="invalid mode"):
            OpenAIResearchAdapter(mode="invalid")

    def test_empty_mode_raises(self):
        with pytest.raises(ValueError):
            OpenAIResearchAdapter(mode="")

    def test_web_search_uses_background_false(self):
        adapter = OpenAIResearchAdapter(mode="web_search")
        assert adapter._config["uses_background"] is False

    def test_deep_research_uses_background_true(self):
        adapter = OpenAIResearchAdapter(mode="deep_research")
        assert adapter._config["uses_background"] is True

    def test_web_search_default_timeout(self):
        adapter = OpenAIResearchAdapter(mode="web_search")
        assert adapter.default_timeout == 300.0

    def test_deep_research_long_timeout(self):
        adapter = OpenAIResearchAdapter(mode="deep_research")
        assert adapter.default_timeout == 1200.0


# ===========================================================================
# B. is_available (공통)
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
# C. Skipped when no key (공통)
# ===========================================================================

class TestSkippedWhenNoKey:
    def test_web_search_skipped(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = OpenAIResearchAdapter(mode="web_search").research("q")
        assert result.status == STATUS_SKIPPED

    def test_deep_research_skipped(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = OpenAIResearchAdapter(mode="deep_research").research("q")
        assert result.status == STATUS_SKIPPED


# ===========================================================================
# D. Web Search 모드 (기존 하위호환)
# ===========================================================================

class TestWebSearchPayload:
    def test_payload_structure(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-abc")
        adapter = OpenAIResearchAdapter(mode="web_search")

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return _mock_success(text="ok")

        with patch(_HTTPX_POST_PATCH, side_effect=capture):
            adapter.research("질문", timeout=60)

        assert captured["url"] == "https://api.openai.com/v1/responses"
        assert captured["headers"]["Authorization"] == "Bearer sk-abc"
        assert captured["timeout"] == 60

        payload = captured["json"]
        assert payload["model"] == "gpt-5.4"
        assert payload["input"][1]["content"][0]["text"] == "질문"
        assert {"type": "web_search_preview"} in payload["tools"]
        # background 필드 없어야 함
        assert "background" not in payload

    def test_env_override_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("OPENAI_RESEARCH_MODEL", "gpt-4o")
        adapter = OpenAIResearchAdapter(mode="web_search")

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success(text="ok")

        with patch(_HTTPX_POST_PATCH, side_effect=capture):
            adapter.research("q")

        assert captured["json"]["model"] == "gpt-4o"

    def test_blank_env_uses_default(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("OPENAI_RESEARCH_MODEL", "   ")
        adapter = OpenAIResearchAdapter(mode="web_search")

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_success(text="ok")

        with patch(_HTTPX_POST_PATCH, side_effect=capture):
            adapter.research("q")

        assert captured["json"]["model"] == "gpt-5.4"


class TestWebSearchSuccess:
    def test_basic_success(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")

        with patch(_HTTPX_POST_PATCH, return_value=_mock_success(
            text="# 보고서\n\n내용",
            annotations=[
                {"type": "url_citation", "url": "https://a.com", "title": "A"},
                {"type": "url_citation", "url": "https://b.com", "title": "B"},
            ],
            usage={"input_tokens": 100, "output_tokens": 2000},
        )):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert "보고서" in result.report
        assert len(result.citations) == 2
        assert result.model == "gpt-5.4"
        assert result.cost_usd > 0
        assert result.raw_meta["mode"] == "web_search"

    def test_no_annotations_still_success(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")

        with patch(_HTTPX_POST_PATCH, return_value=_mock_success(text="report")):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.citations == []

    def test_web_search_calls_ignored(self, monkeypatch):
        """output에 web_search_call 섞여있어도 message만 추출."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")

        extra = [
            {"type": "web_search_call", "status": "completed"},
            {"type": "web_search_call", "status": "completed"},
        ]
        with patch(_HTTPX_POST_PATCH, return_value=_mock_success(
            text="final report", extra_outputs=extra
        )):
            result = adapter.research("q")

        assert result.status == STATUS_SUCCESS
        assert result.report == "final report"


class TestWebSearchResponseStatus:
    def test_failed_status(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "r", "status": "failed", "output": [],
        }
        with patch(_HTTPX_POST_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "failed" in (result.error or "")

    def test_cancelled_status(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "r", "status": "cancelled", "output": [],
        }
        with patch(_HTTPX_POST_PATCH, return_value=mock_resp):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED


# ===========================================================================
# E. Deep Research 기본 성공 경로 (신규)
# ===========================================================================

class TestDeepResearchSuccess:
    """DR 모드 기본 폴링 흐름: submit → poll(in_progress) → poll(completed) → parse."""

    def test_submit_then_poll_completes(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-dr")
        adapter = OpenAIResearchAdapter(
            mode="deep_research",
            poll_interval=0.01,  # 테스트 속도 위해 짧게
            max_wait=10.0,
        )

        # submit: queued 상태
        submit_resp = _mock_queued("resp_dr_123")

        # 폴링 2번: in_progress → completed
        in_progress = _mock_polling_status("in_progress", "resp_dr_123")
        completed = _mock_success(
            text="# Deep Research 보고서\n\n내용",
            annotations=[
                {"type": "url_citation", "url": "https://src1.com", "title": "S1"},
                {"type": "url_citation", "url": "https://src2.com", "title": "S2"},
            ],
            usage={"input_tokens": 200, "output_tokens": 5000},
            response_id="resp_dr_123",
            status="completed",
        )

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, side_effect=[in_progress, completed]), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("커피 로스팅 심층 분석")

        assert result.status == STATUS_SUCCESS
        assert "Deep Research" in result.report
        assert len(result.citations) == 2
        assert result.model == "o4-mini-deep-research-2025-06-26"
        assert result.raw_meta["mode"] == "deep_research"
        assert result.raw_meta["response_id"] == "resp_dr_123"
        # 200×2/1M + 5000×8/1M = 0.0004 + 0.04 = 0.0404
        assert result.cost_usd == pytest.approx(0.0404, abs=1e-4)

    def test_immediate_completion(self, monkeypatch):
        """첫 폴링에서 바로 completed."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        submit_resp = _mock_queued("r1")
        completed = _mock_success(
            text="결과", usage={"input_tokens": 100, "output_tokens": 500},
            response_id="r1", status="completed",
        )

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, return_value=completed), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("q")

        assert result.is_success

    def test_submit_payload_has_background(self, monkeypatch):
        """DR 요청 시 payload에 background=true 포함."""
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        captured = {}

        def capture_submit(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_queued("r1")

        completed = _mock_success(text="ok", response_id="r1", status="completed")

        with patch(_HTTPX_POST_PATCH, side_effect=capture_submit), \
             patch(_HTTPX_GET_PATCH, return_value=completed), \
             patch(_TIME_SLEEP_PATCH):
            adapter.research("q")

        assert captured["json"]["background"] is True
        assert captured["json"]["model"] == "o4-mini-deep-research-2025-06-26"
        assert {"type": "web_search_preview"} in captured["json"]["tools"]

    def test_dr_env_override_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setenv("OPENAI_DEEP_RESEARCH_MODEL", "o3-deep-research-2025-06-26")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=10.0,
        )

        captured = {}

        def capture(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _mock_queued("r1")

        completed = _mock_success(text="ok", response_id="r1", status="completed")

        with patch(_HTTPX_POST_PATCH, side_effect=capture), \
             patch(_HTTPX_GET_PATCH, return_value=completed), \
             patch(_TIME_SLEEP_PATCH):
            adapter.research("q")

        assert captured["json"]["model"] == "o3-deep-research-2025-06-26"


# ===========================================================================
# F. _extract_message_content (기존 그대로)
# ===========================================================================

class TestExtractMessageContent:
    def test_single_message(self):
        output = [_build_message_output("hello", [])]
        text, citations = _extract_message_content(output)
        assert text == "hello"
        assert citations == []

    def test_multiple_messages_last_wins(self):
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
        output = [{"type": "message", "content": []}]
        text, _ = _extract_message_content(output)
        assert text == ""

    def test_missing_content_field(self):
        output = [{"type": "message"}]
        text, _ = _extract_message_content(output)
        assert text == ""


# ===========================================================================
# G. _parse_annotations (기존 그대로)
# ===========================================================================

class TestParseAnnotations:
    def test_url_citations(self):
        result = _parse_annotations([
            {"type": "url_citation", "url": "https://a", "title": "A"},
            {"type": "url_citation", "url": "https://b"},
        ])
        assert len(result) == 2

    def test_non_url_citation_skipped(self):
        result = _parse_annotations([
            {"type": "url_citation", "url": "https://a"},
            {"type": "file_citation", "file_id": "f_123"},
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
# H. 비용 계산 — 모드별 (시그니처 변경)
# ===========================================================================

class TestCalculateCostWebSearch:
    def _config(self):
        return _MODE_CONFIG[MODE_WEB_SEARCH]

    def test_basic_formula(self):
        # 1000 input + 2000 output × gpt-5.4 ($2.50 / $15)
        cost = _calculate_cost(
            {"input_tokens": 1000, "output_tokens": 2000},
            self._config(),
        )
        # 0.0025 + 0.030 = 0.0325
        assert cost == pytest.approx(0.0325, abs=1e-6)


class TestCalculateCostDeepResearch:
    def _config(self):
        return _MODE_CONFIG[MODE_DEEP_RESEARCH]

    def test_basic_formula(self):
        # 1000 input + 2000 output × o4-mini-DR ($2 / $8)
        cost = _calculate_cost(
            {"input_tokens": 1000, "output_tokens": 2000},
            self._config(),
        )
        # 0.002 + 0.016 = 0.018
        assert cost == pytest.approx(0.018, abs=1e-6)


class TestCalculateCostDefensive:
    def _any_config(self):
        return _MODE_CONFIG[MODE_WEB_SEARCH]

    def test_zero_usage(self):
        assert _calculate_cost({}, self._any_config()) == 0.0
        assert _calculate_cost(None, self._any_config()) == 0.0

    def test_non_dict(self):
        assert _calculate_cost("x", self._any_config()) == 0.0

    def test_negative_clamped(self):
        assert _calculate_cost(
            {"input_tokens": -100, "output_tokens": -50},
            self._any_config(),
        ) == 0.0

    def test_none_values(self):
        assert _calculate_cost(
            {"input_tokens": None, "output_tokens": None},
            self._any_config(),
        ) == 0.0

    def test_string_coerced(self):
        cost = _calculate_cost(
            {"input_tokens": "1000", "output_tokens": "500"},
            self._any_config(),
        )
        expected = (1000 * 2.5 + 500 * 15) / 1_000_000.0
        assert cost == pytest.approx(expected)

    def test_prompt_tokens_ignored(self):
        """OpenAI Responses API는 input_tokens/output_tokens만 사용."""
        cost = _calculate_cost(
            {"prompt_tokens": 1000, "completion_tokens": 1000},
            self._any_config(),
        )
        assert cost == 0.0


# ===========================================================================
# I. HTTP 에러 (web_search 모드)
# ===========================================================================

class TestWebSearchHTTPErrors:
    def test_401(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "bad")
        adapter = OpenAIResearchAdapter(mode="web_search")

        with patch(_HTTPX_POST_PATCH, return_value=_mock_error(401)):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "401" in (result.error or "")

    def test_500(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")

        with patch(_HTTPX_POST_PATCH, return_value=_mock_error(500)):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED

    def test_network_exception(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        adapter = OpenAIResearchAdapter(mode="web_search")
        import httpx

        with patch(_HTTPX_POST_PATCH, side_effect=httpx.ConnectError("refused")):
            result = adapter.research("q")

        assert result.status == STATUS_FAILED
        assert "ConnectError" in (result.error or "")


# ===========================================================================
# J. 실사용 시나리오
# ===========================================================================

class TestRealisticScenario:
    def test_web_search_realistic(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
        adapter = OpenAIResearchAdapter(mode="web_search")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "resp_abc", "status": "completed",
            "output": [
                {"type": "web_search_call", "status": "completed"},
                _build_message_output(
                    "# Coffee Roasting\n\n## Stages\n1. Drying\n2. Maillard",
                    annotations=[
                        {"type": "url_citation", "url": "https://scaa.org", "title": "SCAA"},
                    ],
                ),
            ],
            "usage": {"input_tokens": 150, "output_tokens": 2500},
        }

        with patch(_HTTPX_POST_PATCH, return_value=mock_resp):
            result = adapter.research("커피 로스팅")

        assert result.is_success
        assert result.model == "gpt-5.4"
        # 150×2.5/1M + 2500×15/1M = 0.000375 + 0.0375 = 0.037875
        assert result.cost_usd == pytest.approx(0.037875, abs=1e-5)

    def test_deep_research_realistic(self, monkeypatch):
        """DR 전체 흐름: submit → 3회 폴링(in_progress) → completed."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
        adapter = OpenAIResearchAdapter(
            mode="deep_research", poll_interval=0.01, max_wait=60.0,
        )

        submit_resp = _mock_queued("resp_dr_xyz")
        in_progress_resp = _mock_polling_status("in_progress", "resp_dr_xyz")
        completed_resp = _mock_success(
            text="# Deep Coffee Report\n\n[15 sources, 3000 words]",
            annotations=[
                {"type": "url_citation", "url": f"https://source{i}.com", "title": f"S{i}"}
                for i in range(5)
            ],
            usage={"input_tokens": 300, "output_tokens": 4500},
            response_id="resp_dr_xyz",
            status="completed",
        )

        # 첫 2번 폴링 in_progress, 3번째에 completed
        get_responses = [in_progress_resp, in_progress_resp, completed_resp]

        with patch(_HTTPX_POST_PATCH, return_value=submit_resp), \
             patch(_HTTPX_GET_PATCH, side_effect=get_responses), \
             patch(_TIME_SLEEP_PATCH):
            result = adapter.research("커피 로스팅 심층 분석")

        assert result.is_success
        assert len(result.citations) == 5
        assert result.model == "o4-mini-deep-research-2025-06-26"
        # 300×2/1M + 4500×8/1M = 0.0006 + 0.036 = 0.0366
        assert result.cost_usd == pytest.approx(0.0366, abs=1e-4)
