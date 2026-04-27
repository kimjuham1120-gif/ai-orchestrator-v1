"""
tests/test_step15_build_executor.py — Step 15 A5-2

테스트 대상:
  - execute_steps() 공개 API (call_llm mock)
  - _format_steps_for_prompt(), _format_files_for_prompt(), _format_prior_results() 헬퍼
  - _parse_response() — 파일 파싱 / 절대 경로 거부 / fallback action
  - 엣지케이스: 빈 입력, 잘못된 JSON, prior 누적, content 누락
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.app_dev.build_executor import (
    FileSpec,
    BuildOutput,
    VALID_ACTIONS,
    _format_files_for_prompt,
    _format_prior_results,
    _format_steps_for_prompt,
    _parse_response,
    _strip_json_wrapper,
    execute_steps,
)


# ---------------------------------------------------------------------------
# 헬퍼 — _format_steps_for_prompt
# ---------------------------------------------------------------------------

class TestFormatSteps:

    def test_none(self):
        assert "없음" in _format_steps_for_prompt(None)

    def test_empty(self):
        assert "없음" in _format_steps_for_prompt([])

    def test_single_step(self):
        steps = [{"order": 1, "description": "Vite 셋업", "file_hint": ["package.json"]}]
        text = _format_steps_for_prompt(steps)
        assert "1. Vite 셋업" in text
        assert "package.json" in text

    def test_multiple_steps(self):
        steps = [
            {"order": 1, "description": "A", "file_hint": ["a.py"]},
            {"order": 2, "description": "B", "file_hint": ["b.py", "c.py"]},
        ]
        text = _format_steps_for_prompt(steps)
        assert "1. A" in text
        assert "2. B" in text
        assert "b.py, c.py" in text

    def test_no_file_hint(self):
        steps = [{"order": 1, "description": "X"}]
        text = _format_steps_for_prompt(steps)
        assert "1. X" in text
        assert "미정" in text


# ---------------------------------------------------------------------------
# 헬퍼 — _format_files_for_prompt
# ---------------------------------------------------------------------------

class TestFormatFiles:

    def test_none(self):
        text, n = _format_files_for_prompt(None)
        assert n == 0
        assert "없음" in text

    def test_single_file(self):
        ctx = {"files": [{"filename": "CLAUDE.md", "content": "Rule 1"}]}
        text, n = _format_files_for_prompt(ctx)
        assert n == 1
        assert "CLAUDE.md" in text


# ---------------------------------------------------------------------------
# 헬퍼 — _format_prior_results
# ---------------------------------------------------------------------------

class TestFormatPrior:

    def test_empty(self):
        assert _format_prior_results(None) == ""

    def test_with_files(self):
        prior = [{
            "title": "셋업",
            "summary": "Vite + React 셋업 완료",
            "files": [{"path": "package.json"}, {"path": "vite.config.ts"}],
        }]
        text = _format_prior_results(prior)
        assert "셋업" in text
        assert "package.json" in text
        assert "vite.config.ts" in text


# ---------------------------------------------------------------------------
# 헬퍼 — _strip_json_wrapper
# ---------------------------------------------------------------------------

class TestStripJsonWrapper:

    def test_no_wrapper(self):
        assert _strip_json_wrapper('{"a":1}') == '{"a":1}'

    def test_with_json_wrapper(self):
        assert _strip_json_wrapper('```json\n{"a":1}\n```') == '{"a":1}'

    def test_empty(self):
        assert _strip_json_wrapper("") == ""


# ---------------------------------------------------------------------------
# 헬퍼 — _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:

    def test_empty(self):
        s, f, n, err = _parse_response("")
        assert err is not None
        assert "비어" in err

    def test_invalid_json(self):
        s, f, n, err = _parse_response("not json")
        assert err is not None

    def test_valid_simple(self):
        raw = json.dumps({
            "summary": "Vite 셋업",
            "files": [
                {
                    "action": "create",
                    "path": "package.json",
                    "content": '{"name": "test"}',
                    "reason": "프로젝트 메타",
                },
            ],
            "notes": "",
        })
        s, files, n, err = _parse_response(raw)
        assert err is None
        assert s == "Vite 셋업"
        assert len(files) == 1
        assert files[0].action == "create"
        assert files[0].path == "package.json"
        assert "test" in files[0].content
        assert files[0].reason == "프로젝트 메타"

    def test_multiple_files(self):
        raw = json.dumps({
            "summary": "X",
            "files": [
                {"action": "create", "path": "a.py", "content": "a"},
                {"action": "modify", "path": "b.py", "content": "b"},
                {"action": "create", "path": "c.py", "content": "c"},
            ],
        })
        s, files, n, err = _parse_response(raw)
        assert err is None
        assert len(files) == 3
        assert files[1].action == "modify"

    def test_unknown_action_fallback_to_create(self):
        raw = json.dumps({
            "summary": "X",
            "files": [{"action": "delete", "path": "a.py", "content": ""}],
        })
        s, files, n, err = _parse_response(raw)
        assert err is None
        assert files[0].action == "create"  # delete → create로 fallback

    def test_absolute_path_unix_rejected(self):
        raw = json.dumps({
            "summary": "X",
            "files": [
                {"action": "create", "path": "/etc/passwd", "content": "evil"},
                {"action": "create", "path": "src/ok.py", "content": "good"},
            ],
        })
        s, files, n, err = _parse_response(raw)
        assert err is None
        assert len(files) == 1
        assert files[0].path == "src/ok.py"

    def test_absolute_path_windows_rejected(self):
        raw = json.dumps({
            "summary": "X",
            "files": [
                {"action": "create", "path": "C:/Windows/x", "content": "evil"},
                {"action": "create", "path": "src/ok.py", "content": "good"},
            ],
        })
        s, files, n, err = _parse_response(raw)
        assert err is None
        assert len(files) == 1
        assert files[0].path == "src/ok.py"

    def test_missing_path_skipped(self):
        raw = json.dumps({
            "summary": "X",
            "files": [
                {"action": "create", "content": "no path"},
                {"action": "create", "path": "valid.py", "content": "ok"},
            ],
        })
        s, files, n, err = _parse_response(raw)
        assert err is None
        assert len(files) == 1
        assert files[0].path == "valid.py"

    def test_missing_content_skipped(self):
        raw = json.dumps({
            "summary": "X",
            "files": [
                {"action": "create", "path": "no_content.py"},  # content 없음
                {"action": "create", "path": "valid.py", "content": "ok"},
            ],
        })
        s, files, n, err = _parse_response(raw)
        assert err is None
        assert len(files) == 1
        assert files[0].path == "valid.py"

    def test_with_markdown_wrapper(self):
        raw = '```json\n' + json.dumps({
            "summary": "X",
            "files": [{"action": "create", "path": "a.py", "content": "x"}],
        }) + '\n```'
        s, files, n, err = _parse_response(raw)
        assert err is None
        assert len(files) == 1

    def test_finds_json_in_text(self):
        raw = '여기:\n' + json.dumps({
            "summary": "X",
            "files": [{"action": "create", "path": "a.py", "content": "x"}],
        }) + '\n끝'
        s, files, n, err = _parse_response(raw)
        assert err is None
        assert len(files) == 1

    def test_empty_files_array(self):
        raw = json.dumps({"summary": "X", "files": []})
        s, files, n, err = _parse_response(raw)
        assert err is not None
        assert "비어" in err

    def test_files_not_a_list(self):
        raw = json.dumps({"summary": "X", "files": "not a list"})
        s, files, n, err = _parse_response(raw)
        assert err is not None
        assert "list" in err

    def test_notes_extracted(self):
        raw = json.dumps({
            "summary": "X",
            "files": [{"action": "create", "path": "a.py", "content": "x"}],
            "notes": "이건 주의해야 함",
        })
        s, files, notes, err = _parse_response(raw)
        assert err is None
        assert notes == "이건 주의해야 함"

    def test_content_non_string_coerced(self):
        """content가 dict/int이면 str로 변환."""
        raw = json.dumps({
            "summary": "X",
            "files": [
                {"action": "create", "path": "a.py", "content": 12345},
            ],
        })
        s, files, n, err = _parse_response(raw)
        assert err is None
        assert files[0].content == "12345"


# ---------------------------------------------------------------------------
# 공개 API — execute_steps (LLM mock)
# ---------------------------------------------------------------------------

class TestExecuteSteps:

    def test_invalid_todo_not_dict(self):
        result = execute_steps("not dict", [{"order": 1, "description": "X"}], None, None)
        assert not result.ok
        assert "dict" in result.error

    def test_no_title(self):
        result = execute_steps({"id": "x"}, [{"order": 1, "description": "X"}], None, None)
        assert not result.ok
        assert "title" in result.error

    def test_no_steps(self):
        result = execute_steps({"title": "X"}, [], None, None)
        assert not result.ok
        assert "steps" in result.error

    @patch("src.app_dev.build_executor.call_llm")
    def test_llm_returns_none(self, mock_llm):
        mock_llm.return_value = None
        result = execute_steps({"title": "X"}, [{"order": 1, "description": "step"}], None, None)
        assert not result.ok
        assert "LLM 호출 실패" in result.error

    @patch("src.app_dev.build_executor.call_llm")
    def test_successful_call(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "summary": "Vite 셋업 완료",
            "files": [
                {
                    "action": "create",
                    "path": "package.json",
                    "content": '{"name": "test"}',
                    "reason": "메타",
                },
                {
                    "action": "create",
                    "path": "vite.config.ts",
                    "content": "export default {};",
                    "reason": "Vite 설정",
                },
            ],
        })

        todo = {
            "id": "todo-1",
            "title": "프로젝트 셋업",
            "description": "Vite + React",
            "type": "setup",
        }
        steps = [
            {"order": 1, "description": "package.json"},
            {"order": 2, "description": "vite.config.ts"},
        ]

        result = execute_steps(todo, steps, None, None)
        assert result.ok
        assert result.summary == "Vite 셋업 완료"
        assert len(result.files) == 2
        assert result.files[0].path == "package.json"
        assert result.files[1].path == "vite.config.ts"

    @patch("src.app_dev.build_executor.call_llm")
    def test_invalid_json_preserves_raw(self, mock_llm):
        mock_llm.return_value = "I am not JSON"
        result = execute_steps(
            {"title": "X"}, [{"order": 1, "description": "step"}], None, None
        )
        assert not result.ok
        assert result.raw_response == "I am not JSON"

    @patch("src.app_dev.build_executor.call_llm")
    def test_steps_in_prompt(self, mock_llm):
        """steps의 description이 LLM 프롬프트에 들어가는지."""
        mock_llm.return_value = json.dumps({
            "summary": "X",
            "files": [{"action": "create", "path": "a.py", "content": "x"}],
        })
        steps = [{"order": 1, "description": "DISTINCTIVE_STEP_DESC_77"}]
        execute_steps({"title": "Y"}, steps, None, None)

        prompt = mock_llm.call_args[0][0]
        assert "DISTINCTIVE_STEP_DESC_77" in prompt

    @patch("src.app_dev.build_executor.call_llm")
    def test_referenced_context_in_prompt(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "summary": "X",
            "files": [{"action": "create", "path": "a.py", "content": "x"}],
        })

        ctx = {"files": [{"filename": "MARKER.md", "content": "DISTINCT_RULE_88"}]}
        execute_steps(
            {"title": "Test"},
            [{"order": 1, "description": "step"}],
            ctx,
            None,
        )

        prompt = mock_llm.call_args[0][0]
        assert "MARKER.md" in prompt
        assert "DISTINCT_RULE_88" in prompt

    @patch("src.app_dev.build_executor.call_llm")
    def test_prior_results_in_prompt(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "summary": "X",
            "files": [{"action": "create", "path": "a.py", "content": "x"}],
        })

        prior = [{"title": "PRIOR_TITLE_99", "summary": "...", "files": []}]
        execute_steps(
            {"title": "Test"},
            [{"order": 1, "description": "step"}],
            None,
            prior,
        )

        prompt = mock_llm.call_args[0][0]
        assert "PRIOR_TITLE_99" in prompt
        assert "이전 완료" in prompt


# ---------------------------------------------------------------------------
# 직렬화
# ---------------------------------------------------------------------------

class TestSerialization:

    def test_file_spec_to_dict(self):
        f = FileSpec(action="create", path="a.py", content="x", reason="y")
        d = f.to_dict()
        assert d == {"action": "create", "path": "a.py", "content": "x", "reason": "y"}

    def test_build_output_to_dict(self):
        result = BuildOutput(
            summary="test",
            files=[FileSpec(action="create", path="a.py", content="x")],
            notes="note",
        )
        d = result.to_dict()
        assert d["summary"] == "test"
        assert len(d["files"]) == 1
        assert d["notes"] == "note"
        assert d["error"] is None
        assert "raw_response" not in d


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

class TestConstants:

    def test_valid_actions(self):
        assert "create" in VALID_ACTIONS
        assert "modify" in VALID_ACTIONS
        # delete 같은 건 제외
        assert "delete" not in VALID_ACTIONS
