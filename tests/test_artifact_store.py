"""Artifact store 일관 직렬화/역직렬화 테스트."""
from src.store.artifact_store import (
    save_artifact, load_artifact, update_artifact,
    update_approval, update_execution_result, update_final_summary,
    serialize, deserialize,
)


def test_serialize_deserialize_dict():
    d = {"a": 1, "b": [2, 3]}
    s = serialize(d)
    assert isinstance(s, str)
    assert deserialize(s) == d


def test_serialize_none():
    assert serialize(None) is None
    assert deserialize(None) is None


def test_serialize_empty_string():
    assert serialize("") is None
    assert deserialize("") is None


def test_serialize_plain_string():
    assert serialize("hello") == "hello"
    assert deserialize("hello") == "hello"


def test_save_and_load_artifact(tmp_path):
    db = str(tmp_path / "test.db")
    save_artifact(db, {
        "run_id": "run-001",
        "thread_id": "thread-001",
        "task_type": "code_fix",
        "plan": [{"step": 1, "description": "분석"}],
        "approval_required": True,
        "canonical_frozen": False,
        "run_status": "classified",
    })
    loaded = load_artifact(db, run_id="run-001")
    assert loaded is not None
    assert loaded["task_type"] == "code_fix"
    assert loaded["plan"] == [{"step": 1, "description": "분석"}]
    assert loaded["approval_required"] is True
    assert loaded["canonical_frozen"] is False


def test_update_artifact_partial(tmp_path):
    db = str(tmp_path / "test.db")
    save_artifact(db, {"run_id": "run-002", "run_status": "classified"})
    update_artifact(db, "run-002", {"run_status": "approved", "approval_status": "approved"})
    loaded = load_artifact(db, run_id="run-002")
    assert loaded["run_status"] == "approved"
    assert loaded["approval_status"] == "approved"


def test_json_columns_consistent(tmp_path):
    """모든 JSON 컬럼이 동일한 규칙으로 직렬화/역직렬화됨"""
    db = str(tmp_path / "test.db")
    complex_data = {
        "run_id": "run-003",
        "research_bundle": {"claims": [{"a": 1}]},
        "plan": [{"step": 1}],
        "selected_models": {"planner": "gpt-4o"},
        "builder_output": [{"step": 1, "action": "test"}],
        "reviewer_feedback": ["ok", "pass"],
        "execution_result": {"changed_files": ["a.py"]},
        "execution_packet": {"run_id": "run-003"},
        "spec_alignment": {"aligned": True},
    }
    save_artifact(db, complex_data)
    loaded = load_artifact(db, run_id="run-003")
    assert loaded["research_bundle"] == {"claims": [{"a": 1}]}
    assert loaded["plan"] == [{"step": 1}]
    assert loaded["selected_models"] == {"planner": "gpt-4o"}
    assert loaded["reviewer_feedback"] == ["ok", "pass"]
    assert loaded["execution_result"] == {"changed_files": ["a.py"]}


def test_update_approval(tmp_path):
    db = str(tmp_path / "test.db")
    save_artifact(db, {"run_id": "run-004", "run_status": "pending"})
    update_approval(db, "run-004", status="approved", reason="user_approved")
    loaded = load_artifact(db, run_id="run-004")
    assert loaded["approval_status"] == "approved"
    assert loaded["run_status"] == "approved"


def test_update_execution_result(tmp_path):
    db = str(tmp_path / "test.db")
    save_artifact(db, {"run_id": "run-005", "run_status": "packet_ready"})
    update_execution_result(db, "run-005", ["a.py"], "1 passed", "fixed")
    loaded = load_artifact(db, run_id="run-005")
    assert loaded["execution_result"]["changed_files"] == ["a.py"]
    assert loaded["run_status"] == "execution_result_received"


def test_update_final_summary(tmp_path):
    db = str(tmp_path / "test.db")
    save_artifact(db, {"run_id": "run-006", "run_status": "verified"})
    update_final_summary(db, "run-006", "completed summary")
    loaded = load_artifact(db, run_id="run-006")
    assert loaded["final_summary"] == "completed summary"
    assert loaded["run_status"] == "completed"


def test_load_by_thread_id(tmp_path):
    db = str(tmp_path / "test.db")
    save_artifact(db, {"run_id": "run-007", "thread_id": "th-007", "task_type": "feature"})
    loaded = load_artifact(db, thread_id="th-007")
    assert loaded is not None
    assert loaded["run_id"] == "run-007"
