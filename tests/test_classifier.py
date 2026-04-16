"""Classifier 5분류 테스트."""
from src.classifier.classifier import classify_request, TASK_TYPES


def test_code_fix_keywords():
    assert classify_request("버그 수정해줘") == "code_fix"
    assert classify_request("fix the login error") == "code_fix"
    assert classify_request("에러 발생") == "code_fix"


def test_feature_keywords():
    assert classify_request("새 기능 추가해줘") == "feature"
    assert classify_request("implement search") == "feature"


def test_research_keywords():
    assert classify_request("시장 조사해줘") == "research"
    assert classify_request("compare frameworks") == "research"


def test_review_keywords():
    assert classify_request("코드 리뷰 해줘") == "review"
    assert classify_request("audit the module") == "review"


def test_unsupported():
    assert classify_request("오늘 날씨 알려줘") == "unsupported"
    assert classify_request("") == "unsupported"


def test_priority_code_fix_over_feature():
    """code_fix 키워드가 있으면 feature보다 우선"""
    assert classify_request("기능 버그 수정") == "code_fix"


def test_all_task_types_valid():
    assert len(TASK_TYPES) == 5
