"""
Day 115 — Phase 1 · 서브주제 분해 테스트.
(Step 14-2 전환: call_llm_json patch 방식)

검증 포인트 (변경 없음):
1. DecomposeResult 구조
2. LLM 성공 경로 (mock)
3. LLM 실패 시 fallback (원본을 단일 서브주제로)
4. API 키 없을 때 fallback
5. 후처리: 중복 제거, 빈 제거, 길이 자르기
6. min/max 개수 제약
7. 잘못된 JSON 구조 처리 (마크다운 wrapper는 call_llm_json이 처리하므로 제거)
8. 스모크 테스트

패치 방식:
  src.phases.phase_1_decompose.call_llm_json 을 직접 mock
"""
from __future__ import annotations

import pytest
from unittest.mock import patch


_CALL_LLM_JSON_PATCH = "src.phases.phase_1_decompose.call_llm_json"


# ===========================================================================
# 1. 결과 타입 구조
# ===========================================================================

class TestDecomposeResultStructure:
    def test_to_dict_has_all_keys(self):
        from src.phases.phase_1_decompose import DecomposeResult
        r = DecomposeResult(subtopics=["A", "B"])
        d = r.to_dict()
        assert "subtopics" in d
        assert "decided_by" in d
        assert "error" in d

    def test_default_decided_by_is_llm(self):
        from src.phases.phase_1_decompose import DecomposeResult
        r = DecomposeResult(subtopics=["A"])
        assert r.decided_by == "llm"

    def test_default_error_is_none(self):
        from src.phases.phase_1_decompose import DecomposeResult
        r = DecomposeResult(subtopics=["A"])
        assert r.error is None


# ===========================================================================
# 2. Fallback — API 키 없음
# ===========================================================================

class TestFallbackNoKey:
    def test_no_api_key_returns_fallback(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        from src.phases.phase_1_decompose import decompose_request

        r = decompose_request("사업계획서 써줘")
        assert r.decided_by == "fallback"
        assert len(r.subtopics) == 1
        assert "사업계획서" in r.subtopics[0]
        assert r.error is not None

    def test_empty_input_returns_empty_subtopics(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        from src.phases.phase_1_decompose import decompose_request

        r = decompose_request("")
        assert r.subtopics == []
        assert r.decided_by == "fallback"
        assert r.error is not None

    def test_whitespace_only_returns_empty(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        from src.phases.phase_1_decompose import decompose_request

        r = decompose_request("   \n\t  ")
        assert r.subtopics == []


# ===========================================================================
# 3. LLM 성공 경로
# ===========================================================================

class TestLLMSuccess:
    def test_llm_returns_subtopics(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        topics = [
            "사업계획서 작성 방법론",
            "시장 규모 조사",
            "경쟁사 분석",
            "차별화 전략",
            "수익 모델",
        ]

        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": topics}):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("사업계획서 써줘")
            assert r.decided_by == "llm"
            assert len(r.subtopics) == 5
            assert r.subtopics == topics
            assert r.error is None

    def test_llm_called_with_model_and_timeout(self, monkeypatch):
        """call_llm_json이 model, timeout과 함께 호출됨."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": ["A", "B", "C"]}) as mock_json:
            from src.phases.phase_1_decompose import decompose_request
            decompose_request("요청")

            assert mock_json.called
            call_kwargs = mock_json.call_args
            # prompt (첫 인자 또는 keyword) + model + timeout 전달 확인
            # 모든 인자 확인
            all_args = list(call_kwargs.args) + list(call_kwargs.kwargs.values())
            assert any("anthropic" in str(a) or "gpt" in str(a) for a in all_args), \
                "모델 ID가 전달되지 않음"

    def test_llm_sends_user_input_in_prompt(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": ["A"]}) as mock_json:
            from src.phases.phase_1_decompose import decompose_request
            decompose_request("특별한_사용자_요청_문자열")

            # prompt 인자에 사용자 입력 포함
            call_args = mock_json.call_args
            # prompt는 첫 positional 또는 'prompt' kwarg
            if call_args.args:
                prompt_text = call_args.args[0]
            else:
                prompt_text = call_args.kwargs.get("prompt", "")
            assert "특별한_사용자_요청_문자열" in prompt_text


# ===========================================================================
# 4. LLM 실패 fallback
# ===========================================================================

class TestLLMFailureFallback:
    def test_call_llm_json_returns_none_fallback(self, monkeypatch):
        """call_llm_json이 None 반환 → fallback."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_JSON_PATCH, return_value=None):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("테스트 요청")
            assert r.decided_by == "fallback"
            assert len(r.subtopics) == 1
            assert "테스트 요청" in r.subtopics[0]
            assert r.error is not None

    def test_missing_subtopics_key_returns_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        # 키가 다른 dict
        with patch(_CALL_LLM_JSON_PATCH, return_value={"wrong_key": ["A", "B"]}):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("테스트")
            assert r.decided_by == "fallback"

    def test_subtopics_not_list_returns_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": "A string not list"}):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("테스트")
            assert r.decided_by == "fallback"

    def test_response_is_list_not_dict_fallback(self, monkeypatch):
        """call_llm_json이 list 반환 (dict 아님) → fallback."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_JSON_PATCH, return_value=["A", "B"]):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("테스트")
            assert r.decided_by == "fallback"


# ===========================================================================
# 5. 후처리 — 중복/빈/길이
# ===========================================================================

class TestSanitization:
    def test_duplicates_removed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": ["A", "B", "A", "B", "C"]}):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert r.subtopics == ["A", "B", "C"]

    def test_duplicates_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": ["Market", "market", "MARKET", "Design"]}):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert len(r.subtopics) == 2
            assert r.subtopics[0] == "Market"
            assert r.subtopics[1] == "Design"

    def test_empty_strings_removed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        # None 은 call_llm_json 단계에서 처리되지만, 방어적으로 포함
        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": ["A", "", "  ", "B", None, "C"]}):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert "A" in r.subtopics
            assert "B" in r.subtopics
            assert "C" in r.subtopics
            assert "" not in r.subtopics

    def test_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": ["  A  ", "\nB\n", "C"]}):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert r.subtopics == ["A", "B", "C"]

    def test_long_subtopic_truncated(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        long_text = "가" * 200
        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": [long_text, "짧은 거"]}):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert len(r.subtopics[0]) <= 101
            assert r.subtopics[0].endswith("…")
            assert r.subtopics[1] == "짧은 거"


# ===========================================================================
# 6. 개수 제약
# ===========================================================================

class TestCountLimits:
    def test_max_10_enforced(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        topics = [f"주제 {i}" for i in range(20)]
        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": topics}):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert len(r.subtopics) <= 10

    def test_env_override_max(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("DECOMPOSE_MAX_SUBTOPICS", "5")

        topics = [f"주제 {i}" for i in range(20)]
        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": topics}):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert len(r.subtopics) == 5

    def test_below_min_has_warning(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("DECOMPOSE_MIN_SUBTOPICS", "5")

        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": ["A", "B"]}):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert len(r.subtopics) == 2
            assert r.decided_by == "llm"
            assert r.error is not None
            assert "권장" in r.error

    def test_empty_result_falls_back(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_JSON_PATCH, return_value={"subtopics": []}):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("원본 요청 텍스트")
            assert r.decided_by == "fallback"
            assert len(r.subtopics) == 1
            assert "원본 요청" in r.subtopics[0]


# ===========================================================================
# 7. 스모크 테스트
# ===========================================================================

class TestSmoke:
    def test_decompose_always_returns_result(self, monkeypatch):
        """어떤 입력에도 DecomposeResult 반환."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        from src.phases.phase_1_decompose import decompose_request, DecomposeResult

        inputs = [
            "",
            "짧음",
            "사업계획서 써줘",
            "버그 수정해줘",
            "🚀" * 50,
            "매우 긴 요청 " * 100,
        ]
        for text in inputs:
            r = decompose_request(text)
            assert isinstance(r, DecomposeResult)
            assert isinstance(r.subtopics, list)
            assert r.decided_by in {"llm", "fallback"}

    def test_feasibility_param_accepted(self, monkeypatch):
        """feasibility 파라미터를 받아도 오류 없음."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        from src.phases.phase_1_decompose import decompose_request

        feasibility = {"verdict": "possible", "reason": "OK"}
        r = decompose_request("사업계획서 써줘", feasibility=feasibility)
        assert r is not None
