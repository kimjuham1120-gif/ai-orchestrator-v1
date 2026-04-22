"""
Day 115 — Phase 1 · 서브주제 분해 테스트.

검증 포인트:
1. DecomposeResult 구조
2. LLM 성공 경로 (mock)
3. LLM 실패 시 fallback (원본을 단일 서브주제로)
4. API 키 없을 때 fallback
5. 후처리: 중복 제거, 빈 제거, 길이 자르기
6. min/max 개수 제약
7. 마크다운 코드 블록 래핑 해제
8. 잘못된 JSON 구조 처리
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


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
    def _mock_response(self, subtopics_list):
        """LLM 응답을 mock으로 생성."""
        import json as jsonlib
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": jsonlib.dumps({"subtopics": subtopics_list})
                }
            }]
        }
        return mock_resp

    def test_llm_returns_subtopics(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        topics = [
            "사업계획서 작성 방법론",
            "시장 규모 조사",
            "경쟁사 분석",
            "차별화 전략",
            "수익 모델",
        ]
        mock_resp = self._mock_response(topics)

        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("사업계획서 써줘")
            assert r.decided_by == "llm"
            assert len(r.subtopics) == 5
            assert r.subtopics == topics
            assert r.error is None

    def test_llm_called_with_correct_url(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        mock_resp = self._mock_response(["A", "B", "C"])
        with patch.object(httpx, "post", return_value=mock_resp) as mock_post:
            from src.phases.phase_1_decompose import decompose_request
            decompose_request("요청")

            assert mock_post.called
            call_args = mock_post.call_args
            # OpenRouter 엔드포인트 확인
            assert "openrouter.ai" in call_args[0][0]

    def test_llm_sends_user_input_in_prompt(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        mock_resp = self._mock_response(["A"])
        with patch.object(httpx, "post", return_value=mock_resp) as mock_post:
            from src.phases.phase_1_decompose import decompose_request
            decompose_request("특별한_사용자_요청_문자열")

            # 프롬프트에 사용자 입력이 포함되어야 함
            payload = mock_post.call_args[1]["json"]
            prompt_text = payload["messages"][0]["content"]
            assert "특별한_사용자_요청_문자열" in prompt_text


# ===========================================================================
# 4. LLM 실패 fallback
# ===========================================================================

class TestLLMFailureFallback:
    def test_network_error_returns_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        with patch.object(httpx, "post", side_effect=httpx.ConnectError("refused")):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("테스트 요청")
            assert r.decided_by == "fallback"
            assert len(r.subtopics) == 1
            assert "테스트 요청" in r.subtopics[0]
            assert r.error is not None

    def test_http_error_returns_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("500", request=None, response=None)
        )
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("테스트")
            assert r.decided_by == "fallback"

    def test_invalid_json_returns_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "이건 JSON이 아닙니다"}}]
        }
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("테스트")
            assert r.decided_by == "fallback"

    def test_missing_subtopics_key_returns_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx, json as jsonlib

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{
                "message": {"content": jsonlib.dumps({"wrong_key": ["A", "B"]})}
            }]
        }
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("테스트")
            assert r.decided_by == "fallback"

    def test_subtopics_not_list_returns_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx, json as jsonlib

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{
                "message": {"content": jsonlib.dumps({"subtopics": "A string not list"})}
            }]
        }
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("테스트")
            assert r.decided_by == "fallback"


# ===========================================================================
# 5. 후처리 — 중복/빈/길이
# ===========================================================================

class TestSanitization:
    def _mock_response(self, subtopics_list):
        import json as jsonlib
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{
                "message": {"content": jsonlib.dumps({"subtopics": subtopics_list})}
            }]
        }
        return mock_resp

    def test_duplicates_removed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        mock_resp = self._mock_response(["A", "B", "A", "B", "C"])
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert r.subtopics == ["A", "B", "C"]

    def test_duplicates_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        mock_resp = self._mock_response(["Market", "market", "MARKET", "Design"])
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert len(r.subtopics) == 2
            assert r.subtopics[0] == "Market"
            assert r.subtopics[1] == "Design"

    def test_empty_strings_removed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        mock_resp = self._mock_response(["A", "", "  ", "B", None, "C"])
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            # None은 파싱 단계에서 걸러짐, 빈 문자열/공백도
            assert "A" in r.subtopics
            assert "B" in r.subtopics
            assert "C" in r.subtopics
            assert "" not in r.subtopics

    def test_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        mock_resp = self._mock_response(["  A  ", "\nB\n", "C"])
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert r.subtopics == ["A", "B", "C"]

    def test_long_subtopic_truncated(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        long_text = "가" * 200  # 200자
        mock_resp = self._mock_response([long_text, "짧은 거"])
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert len(r.subtopics[0]) <= 101  # 100 + ellipsis
            assert r.subtopics[0].endswith("…")
            assert r.subtopics[1] == "짧은 거"


# ===========================================================================
# 6. 개수 제약
# ===========================================================================

class TestCountLimits:
    def _mock_response(self, subtopics_list):
        import json as jsonlib
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{
                "message": {"content": jsonlib.dumps({"subtopics": subtopics_list})}
            }]
        }
        return mock_resp

    def test_max_10_enforced(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        topics = [f"주제 {i}" for i in range(20)]  # 20개 요청
        mock_resp = self._mock_response(topics)
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert len(r.subtopics) <= 10  # 기본 max

    def test_env_override_max(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("DECOMPOSE_MAX_SUBTOPICS", "5")
        import httpx

        topics = [f"주제 {i}" for i in range(20)]
        mock_resp = self._mock_response(topics)
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert len(r.subtopics) == 5

    def test_below_min_has_warning(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("DECOMPOSE_MIN_SUBTOPICS", "5")
        import httpx

        mock_resp = self._mock_response(["A", "B"])  # 2개 (min=5 아래)
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            # 개수는 부족하지만 있는 만큼 반환, error에 경고 기록
            assert len(r.subtopics) == 2
            assert r.decided_by == "llm"
            assert r.error is not None
            assert "권장" in r.error

    def test_empty_result_falls_back(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        mock_resp = self._mock_response([])  # LLM이 빈 배열 반환
        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("원본 요청 텍스트")
            # 빈 결과 → fallback 모드로 원본을 단일 서브주제
            assert r.decided_by == "fallback"
            assert len(r.subtopics) == 1
            assert "원본 요청" in r.subtopics[0]


# ===========================================================================
# 7. 마크다운 코드 블록 래핑 해제
# ===========================================================================

class TestMarkdownUnwrap:
    def test_json_in_code_block_parsed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx, json as jsonlib

        wrapped = "```json\n" + jsonlib.dumps({
            "subtopics": ["A", "B", "C"]
        }) + "\n```"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": wrapped}}]
        }

        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert r.subtopics == ["A", "B", "C"]
            assert r.decided_by == "llm"

    def test_json_in_plain_code_block_parsed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx, json as jsonlib

        wrapped = "```\n" + jsonlib.dumps({"subtopics": ["X"]}) + "\n```"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": wrapped}}]
        }

        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_1_decompose import decompose_request
            r = decompose_request("요청")
            assert r.subtopics == ["X"]


# ===========================================================================
# 8. 스모크 테스트
# ===========================================================================

class TestSmoke:
    def test_decompose_always_returns_result(self, monkeypatch):
        """어떤 입력에도 DecomposeResult 반환, 예외 전파 없음."""
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
        # feasibility는 현재 참고용, 결과에 직접 영향 없음
        assert r is not None
