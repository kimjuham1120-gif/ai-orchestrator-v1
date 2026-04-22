"""
Day 114 — Phase 0.5 · 처리 가능성 게이트 테스트.

검증 포인트:
1. 규칙 기반 판정 (빈/짧은 입력, 범위 밖, 모호, 명확)
2. LLM 기반 판정 (규칙으로 결정 안 되는 경우)
3. LLM 실패 시 안전한 fallback
4. 결과 타입 (FeasibilityResult)
5. decided_by 필드로 1단계/2단계 추적 가능
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ===========================================================================
# 1. FeasibilityResult 구조
# ===========================================================================

class TestFeasibilityResultStructure:
    def test_to_dict_has_all_keys(self):
        from src.phases.phase_0_5_gate import FeasibilityResult, VERDICT_POSSIBLE
        result = FeasibilityResult(
            verdict=VERDICT_POSSIBLE,
            reason="테스트",
        )
        d = result.to_dict()
        assert "verdict" in d
        assert "reason" in d
        assert "suggested_clarification" in d
        assert "decided_by" in d

    def test_default_decided_by_is_rule(self):
        from src.phases.phase_0_5_gate import FeasibilityResult, VERDICT_POSSIBLE
        result = FeasibilityResult(verdict=VERDICT_POSSIBLE, reason="x")
        assert result.decided_by == "rule"


# ===========================================================================
# 2. 규칙 기반 — 빈/짧은 입력
# ===========================================================================

class TestRuleEmptyInput:
    def test_empty_string_ambiguous(self):
        from src.phases.phase_0_5_gate import check_feasibility, VERDICT_AMBIGUOUS
        r = check_feasibility("")
        assert r.verdict == VERDICT_AMBIGUOUS
        assert r.decided_by == "rule"
        assert r.suggested_clarification is not None

    def test_whitespace_only_ambiguous(self):
        from src.phases.phase_0_5_gate import check_feasibility, VERDICT_AMBIGUOUS
        r = check_feasibility("   \n\t  ")
        assert r.verdict == VERDICT_AMBIGUOUS
        assert r.decided_by == "rule"

    def test_too_short_ambiguous(self):
        from src.phases.phase_0_5_gate import check_feasibility, VERDICT_AMBIGUOUS
        r = check_feasibility("안녕")  # 2자
        assert r.verdict == VERDICT_AMBIGUOUS
        assert r.decided_by == "rule"


# ===========================================================================
# 3. 규칙 기반 — 범위 밖 (out_of_scope)
# ===========================================================================

class TestRuleOutOfScope:
    @pytest.mark.parametrize("text,label", [
        ("오늘 날씨 알려줘", "실시간 날씨"),
        ("지금 비트코인 시세 알려줘", "실시간 금융"),
        ("실시간 뉴스 보여줘", "실시간 뉴스"),
        ("치킨 주문해줘", "물리 주문"),
        ("택시 불러줘", "택시 호출"),
        ("내 이메일 확인해줘", "개인 이메일"),
        ("내 캘린더 일정 보여줘", "개인 캘린더"),
        ("강아지 그림 그려줘", "이미지 생성"),
        ("노래 만들어줘", "음악 생성"),
        ("음성 합성해줘", "음성 합성"),
        ("같이 게임 하자", "게임 상대"),
    ])
    def test_out_of_scope_patterns(self, text, label):
        from src.phases.phase_0_5_gate import check_feasibility, VERDICT_OUT_OF_SCOPE
        r = check_feasibility(text)
        assert r.verdict == VERDICT_OUT_OF_SCOPE, f"{label}: {text} → {r.verdict}"
        assert r.decided_by == "rule"
        assert r.reason  # 이유 비어있지 않음


# ===========================================================================
# 4. 규칙 기반 — 모호 (ambiguous)
# ===========================================================================

class TestRuleAmbiguous:
    @pytest.mark.parametrize("text", [
        "뭐 시켜줘",
        "아무거나 해줘",
        "랜덤 추천해줘",
        "심심해",
        "몰라",
    ])
    def test_ambiguous_patterns(self, text):
        from src.phases.phase_0_5_gate import check_feasibility, VERDICT_AMBIGUOUS
        r = check_feasibility(text)
        assert r.verdict == VERDICT_AMBIGUOUS
        assert r.suggested_clarification is not None


# ===========================================================================
# 5. 규칙 기반 — 명확히 possible
# ===========================================================================

class TestRulePossible:
    @pytest.mark.parametrize("text,label", [
        ("사업계획서 써줘", "사업계획서"),
        ("시장 조사해줘", "조사"),
        ("전략 수립해줘", "전략"),
        ("매뉴얼 작성해줘", "매뉴얼"),
        ("로그인 버그 수정해줘", "버그 수정"),
        ("결제 기능 추가해줘", "기능 추가"),
        ("인증 모듈 리팩터링", "리팩터링"),
        ("코드 리뷰 해줘", "코드 리뷰"),
        ("재고관리 시스템 만들어줘", "시스템 구축"),
        ("API 연동 구현해줘", "기술 구현"),
    ])
    def test_possible_patterns(self, text, label):
        from src.phases.phase_0_5_gate import check_feasibility, VERDICT_POSSIBLE
        r = check_feasibility(text)
        assert r.verdict == VERDICT_POSSIBLE, f"{label}: {text} → {r.verdict}"
        assert r.decided_by == "rule"


# ===========================================================================
# 6. LLM 단계 — 규칙으로 결정 못 하는 경우
# ===========================================================================

class TestLLMFallback:
    def test_unclear_text_no_key_returns_ambiguous(self, monkeypatch):
        """규칙으로 판정 안 되고 API 키 없으면 ambiguous."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        from src.phases.phase_0_5_gate import check_feasibility, VERDICT_AMBIGUOUS
        # 규칙 패턴에 매칭 안 되는 애매한 텍스트
        r = check_feasibility("그거 한번 해보자")
        assert r.verdict == VERDICT_AMBIGUOUS
        assert r.decided_by == "fallback"

    def test_llm_called_when_rule_undecided(self, monkeypatch):
        """규칙으로 판정 안 되면 LLM 호출됨."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx, json as jsonlib

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": jsonlib.dumps({
                        "verdict": "possible",
                        "reason": "문서 작성 요청으로 판정",
                        "suggested_clarification": None,
                    })
                }
            }]
        }

        with patch.object(httpx, "post", return_value=mock_resp) as mock_post:
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_POSSIBLE
            r = check_feasibility("그거 한번 해보자")
            assert mock_post.called
            assert r.verdict == VERDICT_POSSIBLE
            assert r.decided_by == "llm"

    def test_llm_out_of_scope_response(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx, json as jsonlib

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": jsonlib.dumps({
                        "verdict": "out_of_scope",
                        "reason": "실시간 정보 요청",
                        "suggested_clarification": None,
                    })
                }
            }]
        }

        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_OUT_OF_SCOPE
            r = check_feasibility("그거 한번 해보자")
            assert r.verdict == VERDICT_OUT_OF_SCOPE

    def test_llm_network_failure_returns_ambiguous(self, monkeypatch):
        """LLM 네트워크 실패 시 ambiguous로 안전하게 (Phase 0.5 게이트는 예외 금지)."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        with patch.object(httpx, "post", side_effect=httpx.ConnectError("refused")):
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_AMBIGUOUS
            r = check_feasibility("그거 한번 해보자")
            assert r.verdict == VERDICT_AMBIGUOUS
            assert r.decided_by == "fallback"

    def test_llm_invalid_json_returns_ambiguous(self, monkeypatch):
        """LLM이 JSON 아닌 응답 → ambiguous."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "이건 JSON이 아닙니다"}}]
        }

        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_AMBIGUOUS
            r = check_feasibility("그거 한번 해보자")
            assert r.verdict == VERDICT_AMBIGUOUS
            assert r.decided_by == "fallback"

    def test_llm_markdown_wrapped_json_parses(self, monkeypatch):
        """LLM이 ```json 코드 블록으로 감싼 응답도 파싱."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx, json as jsonlib

        wrapped = "```json\n" + jsonlib.dumps({
            "verdict": "possible",
            "reason": "OK",
            "suggested_clarification": None,
        }) + "\n```"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": wrapped}}]
        }

        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_POSSIBLE
            r = check_feasibility("그거 한번 해보자")
            assert r.verdict == VERDICT_POSSIBLE

    def test_llm_invalid_verdict_defaults_to_ambiguous(self, monkeypatch):
        """LLM이 이상한 verdict 값 반환 → ambiguous."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx, json as jsonlib

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": jsonlib.dumps({
                        "verdict": "definitely_yes",  # 잘못된 값
                        "reason": "x",
                    })
                }
            }]
        }

        with patch.object(httpx, "post", return_value=mock_resp):
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_AMBIGUOUS
            r = check_feasibility("애매한 입력")
            assert r.verdict == VERDICT_AMBIGUOUS


# ===========================================================================
# 7. 우선순위 — 규칙이 LLM보다 먼저
# ===========================================================================

class TestRulePrecedence:
    def test_rule_matches_skips_llm(self, monkeypatch):
        """규칙으로 판정되면 LLM 호출 안 함."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        with patch.object(httpx, "post") as mock_post:
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_POSSIBLE
            r = check_feasibility("사업계획서 써줘")
            assert r.verdict == VERDICT_POSSIBLE
            assert r.decided_by == "rule"
            assert not mock_post.called  # LLM 호출 없음

    def test_out_of_scope_rule_skips_llm(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        import httpx

        with patch.object(httpx, "post") as mock_post:
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_OUT_OF_SCOPE
            r = check_feasibility("오늘 날씨 알려줘")
            assert r.verdict == VERDICT_OUT_OF_SCOPE
            assert r.decided_by == "rule"
            assert not mock_post.called


# ===========================================================================
# 8. 전체 워크플로우 스모크 테스트
# ===========================================================================

class TestSmoke:
    def test_check_feasibility_always_returns_result(self):
        """check_feasibility는 어떤 입력에도 FeasibilityResult 반환 (예외 전파 없음)."""
        from src.phases.phase_0_5_gate import check_feasibility, FeasibilityResult
        inputs = [
            "",
            "x",
            "사업계획서 써줘",
            "오늘 날씨",
            "뭐 시켜줘",
            "일반적인 텍스트이지만 규칙에 안 잡힘",
            "🚀✨" * 100,  # 이모지 폭탄
        ]
        for text in inputs:
            r = check_feasibility(text)
            assert isinstance(r, FeasibilityResult)
            assert r.verdict in {"possible", "out_of_scope", "ambiguous"}
            assert r.decided_by in {"rule", "llm", "fallback"}
