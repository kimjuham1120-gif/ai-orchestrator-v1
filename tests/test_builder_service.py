"""Builder 서비스 테스트."""
import os
from unittest.mock import patch
from src.builder.builder_service import run_builder
from src.builder.builder_schema import BUILDER_STATUS_CREATED


def test_builder_no_api_key_returns_fake():
    with patch.dict(os.environ, {}, clear=True):
        result, model_id = run_builder("버그 수정해줘", "code_fix", [])
    assert result.builder_status == BUILDER_STATUS_CREATED
    assert len(result.builder_output) > 0
    assert model_id is None


def test_builder_state_dict_structure():
    with patch.dict(os.environ, {}, clear=True):
        result, _ = run_builder("에러 수정", "code_fix", [{"step": 1, "description": "분석"}])
    d = result.to_state_dict()
    assert "builder_output" in d
    assert isinstance(d["builder_output"], list)
    assert all("step" in s and "action" in s for s in d["builder_output"])
