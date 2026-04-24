"""
Day 114 — Phase 0.5 · 처리 가능성 게이트 테스트.
(Step 14-2 전환: call_llm_json patch 방식)

검증 포인트 (변경 없음):
1. 규칙 기반 판정 (빈/짧은 입력, 범위 밖, 모호, 명확)
2. LLM 기반 판정 (규칙으로 결정 안 되는 경우)
3. LLM 실패 시 안전한 fallback
4. 결과 타입 (FeasibilityResult)
5. decided_by 필드로 1단계/2단계 추적 가능

패치 방식:
  src.phases.phase_0_5_gate.call_llm_json 을 직접 mock
  (httpx.post patch 방식은 deprecated — call_llm_json이 내부 재시도·캐싱 담당)
"""
from __future__ import annotations

import pytest
from unittest.mock import patch


_CALL_LLM_JSON_PATCH = "src.phases.phase_0_5_gate.call_llm_json"


# ===========================================================================
# 1. FeasibilityResult 구조
# ===========================================================================

class TestFeasibilityResultStructure:
    def test_to_dict_has_all_keys(self):
        from src.phases.phase_0_5_gate import FeasibilityResult, VERDICT_POSSIBLE
        result = FeasibilityResult(verdict=VERDICT_POSSIBLE, reason="테스트")
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
        r = check_feasibility("안녕")
        assert r.verdict == VERDICT_AMBIGUOUS
        assert r.decided_by == "rule"


# ===========================================================================
# 3. 규칙 기반 — 범위 밖
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
        assert r.reason


# ===========================================================================
# 4. 규칙 기반 — 모호
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
# 6. LLM 단계 — call_llm_json 직접 patch
# ===========================================================================

class TestLLMFallback:
    def test_unclear_text_no_key_returns_ambiguous(self, monkeypatch):
        """API 키 없으면 ambiguous fallback."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        from src.phases.phase_0_5_gate import check_feasibility, VERDICT_AMBIGUOUS
        r = check_feasibility("그거 한번 해보자")
        assert r.verdict == VERDICT_AMBIGUOUS
        assert r.decided_by == "fallback"

    def test_llm_called_when_rule_undecided(self, monkeypatch):
        """규칙으로 판정 안 되면 call_llm_json 호출."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        llm_response = {
            "verdict": "possible",
            "reason": "문서 작성 요청으로 판정",
            "suggested_clarification": None,
        }

        with patch(_CALL_LLM_JSON_PATCH, return_value=llm_response) as mock_json:
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_POSSIBLE
            r = check_feasibility("그거 한번 해보자")
            assert mock_json.called
            assert r.verdict == VERDICT_POSSIBLE
            assert r.decided_by == "llm"

    def test_llm_out_of_scope_response(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        llm_response = {
            "verdict": "out_of_scope",
            "reason": "실시간 정보 요청",
            "suggested_clarification": None,
        }

        with patch(_CALL_LLM_JSON_PATCH, return_value=llm_response):
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_OUT_OF_SCOPE
            r = check_feasibility("그거 한번 해보자")
            assert r.verdict == VERDICT_OUT_OF_SCOPE

    def test_llm_network_failure_returns_ambiguous(self, monkeypatch):
        """LLM 실패 시 ambiguous fallback (call_llm_json이 None 반환)."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_JSON_PATCH, return_value=None):
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_AMBIGUOUS
            r = check_feasibility("그거 한번 해보자")
            assert r.verdict == VERDICT_AMBIGUOUS
            assert r.decided_by == "fallback"

    def test_llm_invalid_response_returns_ambiguous(self, monkeypatch):
        """call_llm_json이 dict 아닌 값 반환 → ambiguous fallback."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        # dict가 아닌 응답 (list 등) — call_llm_json은 list도 반환 가능
        with patch(_CALL_LLM_JSON_PATCH, return_value=["잘못된", "응답"]):
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_AMBIGUOUS
            r = check_feasibility("그거 한번 해보자")
            assert r.verdict == VERDICT_AMBIGUOUS
            assert r.decided_by == "fallback"

    def test_llm_invalid_verdict_defaults_to_ambiguous(self, monkeypatch):
        """LLM이 이상한 verdict 값 반환 → ambiguous로 자동 보정."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        llm_response = {
            "verdict": "definitely_yes",  # 잘못된 값
            "reason": "x",
        }

        with patch(_CALL_LLM_JSON_PATCH, return_value=llm_response):
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_AMBIGUOUS
            r = check_feasibility("애매한 입력")
            assert r.verdict == VERDICT_AMBIGUOUS

    def test_llm_missing_reason_uses_default(self, monkeypatch):
        """reason 필드 누락 → 기본 'LLM 판정' 사용."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        llm_response = {"verdict": "possible"}

        with patch(_CALL_LLM_JSON_PATCH, return_value=llm_response):
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_POSSIBLE
            r = check_feasibility("애매한 입력")
            assert r.verdict == VERDICT_POSSIBLE
            assert r.reason  # 어떤 값이든 들어있음
            assert r.decided_by == "llm"


# ===========================================================================
# 7. 우선순위 — 규칙이 LLM보다 먼저
# ===========================================================================

class TestRulePrecedence:
    def test_rule_matches_skips_llm(self, monkeypatch):
        """규칙으로 판정되면 LLM 호출 안 함."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_JSON_PATCH) as mock_json:
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_POSSIBLE
            r = check_feasibility("사업계획서 써줘")
            assert r.verdict == VERDICT_POSSIBLE
            assert r.decided_by == "rule"
            assert not mock_json.called

    def test_out_of_scope_rule_skips_llm(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

        with patch(_CALL_LLM_JSON_PATCH) as mock_json:
            from src.phases.phase_0_5_gate import check_feasibility, VERDICT_OUT_OF_SCOPE
            r = check_feasibility("오늘 날씨 알려줘")
            assert r.verdict == VERDICT_OUT_OF_SCOPE
            assert r.decided_by == "rule"
            assert not mock_json.called


# ===========================================================================
# 8. 스모크 테스트
# ===========================================================================

class TestSmoke:
    def test_check_feasibility_always_returns_result(self):
        """check_feasibility는 어떤 입력에도 FeasibilityResult 반환."""
        from src.phases.phase_0_5_gate import check_feasibility, FeasibilityResult
        inputs = [
            "",
            "x",
            "사업계획서 써줘",
            "오늘 날씨",
            "뭐 시켜줘",
            "일반적인 텍스트이지만 규칙에 안 잡힘",
            "🚀✨" * 100,
        ]
        for text in inputs:
            r = check_feasibility(text)
            assert isinstance(r, FeasibilityResult)
            assert r.verdict in {"possible", "out_of_scope", "ambiguous"}
            assert r.decided_by in {"rule", "llm", "fallback"}
