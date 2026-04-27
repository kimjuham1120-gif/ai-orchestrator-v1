"""
tests/test_step15_build_planner.py — Step 15 A5-1

테스트 대상:
  - plan_todo_steps() 공개 API (call_llm mock)
  - _format_files_for_prompt(), _format_prior_results() 헬퍼
  - _parse_response() JSON 파싱
  - 엣지케이스: 빈 입력, 잘못된 JSON, prior_results 누적
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.app_dev.build_planner import (
    PlanStep,
    StepPlanResult,
    _format_files_for_prompt,
    _format_prior_results,
    _parse_response,
    _strip_json_wrapper,
    plan_todo_steps,
)


# ---------------------------------------------------------------------------
# 헬퍼 — _format_files_for_prompt
# ---------------------------------------------------------------------------

class TestFormatFiles:
    def test_none(self):
        text, n = _format_files_for_prompt(None)
        assert n == 0
        assert "없음" in text

    def test_empty(self):
        text, n = _format_files_for_prompt({})
        assert n == 0

    def test_single_file(self):
        ctx = {"files": [{"filename": "CLAUDE.md", "content": "Rule 1"}]}
        text, n = _format_files_for_prompt(ctx)
        assert n == 1
        assert "CLAUDE.md" in text
        assert "Rule 1" in text

    def test_skips_empty_content(self):
        ctx = {"files": [
            {"filename": "a.md", "content": "Has content"},
            {"filename": "b.md", "content": ""},
            {"filename": "c.md", "content": "More"},
        ]}
        text, n = _format_files_for_prompt(ctx)
        assert n == 2
        assert "b.md" not in text


# ---------------------------------------------------------------------------
# 헬퍼 — _format_prior_results
# ---------------------------------------------------------------------------

class TestFormatPriorResults:
    def test_empty(self):
        assert _format_prior_results(None) == ""
        assert _format_prior_results([]) == ""

    def test_single_prior(self):
        prior = [
            {"title": "프로젝트 셋업", "summary": "Vite + React 셋업 완료",
             "files": [{"path": "package.json"}, {"path": "vite.config.ts"}]},
        ]
        text = _format_prior_results(prior)
        assert "프로젝트 셋업" in text
        assert "Vite + React 셋업 완료" in text
        assert "package.json" in text
        assert "vite.config.ts" in text

    def test_multiple_priors(self):
        prior = [
            {"title": "A", "summary": "...", "files": []},
            {"title": "B", "summary": "...", "files": []},
        ]
        text = _format_prior_results(prior)
        assert "Todo 1: A" in text
        assert "Todo 2: B" in text


# ---------------------------------------------------------------------------
# 헬퍼 — _strip_json_wrapper
# ---------------------------------------------------------------------------

class TestStripJsonWrapper:
    def test_no_wrapper(self):
        assert _strip_json_wrapper('{"a":1}') == '{"a":1}'

    def test_json_wrapper(self):
        assert _strip_json_wrapper('```json\n{"a":1}\n```') == '{"a":1}'

    def test_plain_wrapper(self):
        assert _strip_json_wrapper('```\n{"a":1}\n```') == '{"a":1}'

    def test_empty(self):
        assert _strip_json_wrapper("") == ""
        assert _strip_json_wrapper(None) is None


# ---------------------------------------------------------------------------
# 헬퍼 — _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:

    def test_empty(self):
        summary, steps, err = _parse_response("")
        assert err is not None
        assert "비어" in err

    def test_invalid_json(self):
        summary, steps, err = _parse_response("not json")
        assert err is not None
        assert "JSON" in err

    def test_valid_response(self):
        raw = json.dumps({
            "summary": "Vite + React 셋업",
            "steps": [
                {"order": 1, "description": "package.json 작성", "file_hint": ["package.json"]},
                {"order": 2, "description": "vite.config.ts 작성", "file_hint": ["vite.config.ts"]},
            ],
        })
        summary, steps, err = _parse_response(raw)
        assert err is None
        assert summary == "Vite + React 셋업"
        assert len(steps) == 2
        assert steps[0].order == 1
        assert steps[0].description == "package.json 작성"
        assert steps[0].file_hint == ["package.json"]

    def test_with_markdown_wrapper(self):
        raw = '```json\n' + json.dumps({
            "summary": "X",
            "steps": [{"order": 1, "description": "test"}],
        }) + '\n```'
        summary, steps, err = _parse_response(raw)
        assert err is None
        assert len(steps) == 1

    def test_finds_json_in_text(self):
        raw = '여기 결과:\n\n' + json.dumps({
            "summary": "X",
            "steps": [{"order": 1, "description": "test"}],
        }) + '\n\n끝'
        summary, steps, err = _parse_response(raw)
        assert err is None
        assert len(steps) == 1

    def test_missing_description_skipped(self):
        raw = json.dumps({
            "summary": "X",
            "steps": [
                {"order": 1, "description": "valid"},
                {"order": 2},  # description 없음
                {"order": 3, "description": "valid 2"},
            ],
        })
        summary, steps, err = _parse_response(raw)
        assert err is None
        assert len(steps) == 2

    def test_invalid_order_fallback(self):
        """order가 없거나 잘못되면 인덱스 기반."""
        raw = json.dumps({
            "summary": "X",
            "steps": [
                {"description": "no order"},  # order 없음 → 1
                {"order": "bad", "description": "bad order"},  # str → 2
            ],
        })
        summary, steps, err = _parse_response(raw)
        assert err is None
        assert len(steps) == 2

    def test_steps_not_list(self):
        raw = json.dumps({"summary": "X", "steps": "not a list"})
        summary, steps, err = _parse_response(raw)
        assert err is not None
        assert "list" in err

    def test_no_steps_key(self):
        raw = json.dumps({"summary": "X"})
        summary, steps, err = _parse_response(raw)
        assert err is not None

    def test_empty_steps(self):
        raw = json.dumps({"summary": "X", "steps": []})
        summary, steps, err = _parse_response(raw)
        assert err is not None
        assert "비어" in err

    def test_file_hint_not_list(self):
        raw = json.dumps({
            "summary": "X",
            "steps": [{"order": 1, "description": "test", "file_hint": "single_string.py"}],
        })
        summary, steps, err = _parse_response(raw)
        assert err is None
        assert steps[0].file_hint == []  # str → 무시

    def test_steps_sorted_by_order(self):
        """순서가 뒤섞여 있어도 order 기준 정렬."""
        raw = json.dumps({
            "summary": "X",
            "steps": [
                {"order": 3, "description": "third"},
                {"order": 1, "description": "first"},
                {"order": 2, "description": "second"},
            ],
        })
        summary, steps, err = _parse_response(raw)
        assert err is None
        assert [s.order for s in steps] == [1, 2, 3]
        assert steps[0].description == "first"


# ---------------------------------------------------------------------------
# 공개 API — plan_todo_steps (LLM mock)
# ---------------------------------------------------------------------------

class TestPlanTodoSteps:

    def test_invalid_todo_not_dict(self):
        result = plan_todo_steps("not a dict", None, None)
        assert not result.ok
        assert "dict" in result.error

    def test_todo_no_title(self):
        result = plan_todo_steps({"id": "x", "description": "desc"}, None, None)
        assert not result.ok
        assert "title" in result.error

    @patch("src.app_dev.build_planner.call_llm")
    def test_llm_returns_none(self, mock_llm):
        mock_llm.return_value = None
        result = plan_todo_steps({"title": "X"}, None, None)
        assert not result.ok
        assert "LLM 호출 실패" in result.error

    @patch("src.app_dev.build_planner.call_llm")
    def test_successful_call(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "summary": "프로젝트 셋업",
            "steps": [
                {"order": 1, "description": "package.json 작성", "file_hint": ["package.json"]},
                {"order": 2, "description": "vite.config.ts 작성"},
            ],
        })

        todo = {
            "id": "todo-1",
            "title": "프로젝트 셋업",
            "description": "Vite + React 환경 구성",
            "type": "setup",
            "estimated_files": ["package.json", "vite.config.ts"],
        }

        result = plan_todo_steps(todo, None, None)
        assert result.ok
        assert result.summary == "프로젝트 셋업"
        assert len(result.steps) == 2
        assert result.steps[0].file_hint == ["package.json"]

    @patch("src.app_dev.build_planner.call_llm")
    def test_invalid_json_preserves_raw(self, mock_llm):
        mock_llm.return_value = "I am not JSON"
        result = plan_todo_steps({"title": "X"}, None, None)
        assert not result.ok
        assert result.raw_response == "I am not JSON"

    @patch("src.app_dev.build_planner.call_llm")
    def test_referenced_context_in_prompt(self, mock_llm):
        """referenced_context의 파일 내용이 LLM 프롬프트에 포함되는지."""
        mock_llm.return_value = json.dumps({
            "summary": "X",
            "steps": [{"order": 1, "description": "test"}],
        })

        ctx = {"files": [{"filename": "MARKER_FILE.md", "content": "DISTINCT_CONTENT_99"}]}
        plan_todo_steps({"title": "Test"}, ctx, None)

        called_prompt = mock_llm.call_args[0][0]
        assert "MARKER_FILE.md" in called_prompt
        assert "DISTINCT_CONTENT_99" in called_prompt

    @patch("src.app_dev.build_planner.call_llm")
    def test_prior_results_in_prompt(self, mock_llm):
        """prior_results가 LLM 프롬프트에 포함되는지."""
        mock_llm.return_value = json.dumps({
            "summary": "X",
            "steps": [{"order": 1, "description": "test"}],
        })

        prior = [
            {"title": "DISTINCTIVE_PRIOR_TITLE_42", "summary": "...", "files": []},
        ]
        plan_todo_steps({"title": "Test"}, None, prior)

        called_prompt = mock_llm.call_args[0][0]
        assert "DISTINCTIVE_PRIOR_TITLE_42" in called_prompt
        assert "이전 완료된 Todo" in called_prompt

    @patch("src.app_dev.build_planner.call_llm")
    def test_todo_data_in_prompt(self, mock_llm):
        """Todo의 title/description이 LLM 프롬프트에 포함되는지."""
        mock_llm.return_value = json.dumps({
            "summary": "X",
            "steps": [{"order": 1, "description": "test"}],
        })

        todo = {
            "id": "todo-test",
            "title": "DISTINCTIVE_TITLE_33",
            "description": "DISTINCTIVE_DESC_44",
            "type": "feature",
            "estimated_files": ["UNIQUE_FILE.py"],
        }
        plan_todo_steps(todo, None, None)

        called_prompt = mock_llm.call_args[0][0]
        assert "DISTINCTIVE_TITLE_33" in called_prompt
        assert "DISTINCTIVE_DESC_44" in called_prompt
        assert "UNIQUE_FILE.py" in called_prompt


# ---------------------------------------------------------------------------
# 직렬화
# ---------------------------------------------------------------------------

class TestSerialization:

    def test_plan_step_to_dict(self):
        step = PlanStep(order=1, description="X", file_hint=["a.py"])
        assert step.to_dict() == {
            "order": 1,
            "description": "X",
            "file_hint": ["a.py"],
        }

    def test_step_plan_result_to_dict(self):
        result = StepPlanResult(
            summary="test",
            steps=[PlanStep(order=1, description="X")],
        )
        d = result.to_dict()
        assert d["summary"] == "test"
        assert len(d["steps"]) == 1
        assert d["error"] is None
        # raw_response는 to_dict에서 제외
        assert "raw_response" not in d
