"""검증 계층 테스트 — result_verifier + spec_alignment."""
from src.verification.result_verifier import verify_execution_result
from src.verification.spec_alignment import check_spec_alignment


# --- result_verifier ---

def test_verify_passes_complete():
    result = verify_execution_result({
        "changed_files": ["src/auth.py"],
        "test_results": "2 passed",
        "run_log": "fixed",
    })
    assert result.passed


def test_verify_fails_empty_result():
    result = verify_execution_result(None)
    assert not result.passed


def test_verify_fails_empty_changed_files():
    result = verify_execution_result({
        "changed_files": [],
        "test_results": "ok",
        "run_log": "done",
    })
    assert not result.passed


def test_verify_detects_test_failure():
    result = verify_execution_result({
        "changed_files": ["a.py"],
        "test_results": "1 failed",
        "run_log": "done",
    })
    assert not result.passed
    assert any("실패" in i for i in result.issues)


# --- spec_alignment ---

def test_alignment_passes_basic():
    result = check_spec_alignment(
        execution_result={"changed_files": ["src/auth.py"], "test_results": "ok", "run_log": "done"},
    )
    assert result.aligned


def test_alignment_fails_no_result():
    result = check_spec_alignment(execution_result={})
    assert not result.aligned
    assert result.failure_type == "slice_issue"


def test_alignment_detects_scope_drift():
    spec = {
        "goal": "fix auth",
        "target_files": ["src/auth.py"],
        "constraints": ["scope 이탈 금지"],
    }
    result = check_spec_alignment(
        execution_result={"changed_files": ["src/unrelated.py"]},
        deliverable_spec=spec,
    )
    assert not result.aligned
    assert result.failure_type == "doc_issue"


def test_alignment_slice_issue_vs_doc_issue():
    """changed_files 비어있으면 slice_issue"""
    result = check_spec_alignment(execution_result={"changed_files": []})
    assert result.failure_type == "slice_issue"
