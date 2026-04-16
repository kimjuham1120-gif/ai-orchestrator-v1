"""3층 리뷰 시스템 테스트."""
from src.reviewer.rule_checker import run_rule_check
from src.reviewer.llm_reviewer import run_llm_review
from src.reviewer.review_gate import run_review_gate


def test_rule_check_normal():
    plan = [{"step": 1, "description": "분석"}]
    output = [{"step": 1, "action": "src/auth.py 수정 — 테스트 포인트 확인"}]
    result = run_rule_check(plan, output)
    feedback = result.to_feedback()
    assert len(feedback) == 3
    assert "범위 이탈 없음" in feedback[0]


def test_rule_check_warning():
    output = [{"step": 1, "action": "whole project 대규모 리팩토링 new feature"}]
    result = run_rule_check([], output)
    assert result.has_warnings()


def test_llm_reviewer_stub_passes():
    result = run_llm_review([], [])
    assert result.passed
    assert result.model_used == "stub"


def test_review_gate_passes_clean():
    plan = [{"step": 1, "description": "분석"}]
    output = [{"step": 1, "action": "auth.py 수정 — verify 검증"}]
    gate = run_review_gate(plan, output)
    # rule_check에서 test 키워드 "verify" 있으므로 test_missing은 pass
    # scope/over_modify도 clean
    assert gate.gate_passed is True


def test_review_gate_blocks_on_warning():
    output = [{"step": 1, "action": "whole project new feature 전면 수정"}]
    gate = run_review_gate([], output)
    assert gate.gate_passed is False
    assert gate.block_reason
