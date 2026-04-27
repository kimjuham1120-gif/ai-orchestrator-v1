"""
tests/test_step15_todo_planner.py — Step 15 A3 단위 테스트

테스트 대상:
  - generate_todo_list() 공개 API
  - _format_files_for_prompt() 헬퍼
  - _parse_response() JSON 파싱

테스트 전략:
  - LLM 호출은 모두 mock (call_llm)
  - 파싱 로직은 직접 테스트 (mock 없이)
  - 빈 입력 / 잘못된 JSON / 알 수 없는 type 등 엣지케이스 커버
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.app_dev.todo_planner import (
    TodoItem,
    TodoListResult,
    VALID_TODO_TYPES,
    _format_files_for_prompt,
    _parse_response,
    _strip_json_wrapper,
    generate_todo_list,
)


# ---------------------------------------------------------------------------
# 헬퍼 — _format_files_for_prompt
# ---------------------------------------------------------------------------

class TestFormatFilesForPrompt:
    """referenced_context를 프롬프트 텍스트로 변환."""

    def test_none_input(self):
        text, n = _format_files_for_prompt(None)
        assert n == 0
        assert "없음" in text

    def test_empty_dict(self):
        text, n = _format_files_for_prompt({})
        assert n == 0

    def test_no_files_key(self):
        text, n = _format_files_for_prompt({"uploaded_at": "2026-04-27"})
        assert n == 0

    def test_empty_files_list(self):
        text, n = _format_files_for_prompt({"files": []})
        assert n == 0

    def test_single_file(self):
        ctx = {
            "files": [
                {"filename": "CLAUDE.md", "content": "Hello world"},
            ],
        }
        text, n = _format_files_for_prompt(ctx)
        assert n == 1
        assert "### CLAUDE.md" in text
        assert "Hello world" in text

    def test_multiple_files(self):
        ctx = {
            "files": [
                {"filename": "a.md", "content": "Content A"},
                {"filename": "b.md", "content": "Content B"},
            ],
        }
        text, n = _format_files_for_prompt(ctx)
        assert n == 2
        assert "### a.md" in text
        assert "### b.md" in text
        assert "Content A" in text
        assert "Content B" in text
        # 구분자 포함
        assert "---" in text

    def test_skips_empty_content(self):
        ctx = {
            "files": [
                {"filename": "a.md", "content": "Has content"},
                {"filename": "b.md", "content": ""},  # 빈 내용 — 제외
                {"filename": "c.md", "content": "More content"},
            ],
        }
        text, n = _format_files_for_prompt(ctx)
        assert n == 2  # b.md는 제외됨
        assert "### b.md" not in text


# ---------------------------------------------------------------------------
# 헬퍼 — _strip_json_wrapper
# ---------------------------------------------------------------------------

class TestStripJsonWrapper:
    """LLM이 ```json...```으로 감쌌을 때 제거."""

    def test_no_wrapper(self):
        assert _strip_json_wrapper('{"a": 1}') == '{"a": 1}'

    def test_json_wrapper(self):
        text = '```json\n{"a": 1}\n```'
        assert _strip_json_wrapper(text) == '{"a": 1}'

    def test_plain_wrapper(self):
        text = '```\n{"a": 1}\n```'
        assert _strip_json_wrapper(text) == '{"a": 1}'

    def test_with_whitespace(self):
        text = '\n\n  ```json\n{"a": 1}\n```  \n'
        assert _strip_json_wrapper(text) == '{"a": 1}'

    def test_empty(self):
        assert _strip_json_wrapper("") == ""
        assert _strip_json_wrapper(None) is None


# ---------------------------------------------------------------------------
# 헬퍼 — _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    """LLM 응답 텍스트를 TodoItem 리스트로 파싱."""

    def test_empty_response(self):
        items, err = _parse_response("")
        assert items == []
        assert err is not None
        assert "비어" in err

    def test_invalid_json(self):
        items, err = _parse_response("not valid json at all")
        assert items == []
        assert err is not None
        assert "JSON" in err

    def test_valid_simple_response(self):
        raw = json.dumps({
            "items": [
                {
                    "title": "프로젝트 셋업",
                    "description": "Vite + React 환경 구성",
                    "type": "setup",
                    "estimated_files": ["package.json"],
                },
            ],
        })
        items, err = _parse_response(raw)
        assert err is None
        assert len(items) == 1
        assert items[0].id == "todo-1"
        assert items[0].title == "프로젝트 셋업"
        assert items[0].type == "setup"
        assert items[0].estimated_files == ["package.json"]
        assert items[0].status == "pending"

    def test_multiple_items_get_sequential_ids(self):
        raw = json.dumps({
            "items": [
                {"title": "A", "description": "", "type": "setup"},
                {"title": "B", "description": "", "type": "feature"},
                {"title": "C", "description": "", "type": "engine"},
            ],
        })
        items, err = _parse_response(raw)
        assert err is None
        assert len(items) == 3
        assert [t.id for t in items] == ["todo-1", "todo-2", "todo-3"]

    def test_unknown_type_fallback_to_feature(self):
        raw = json.dumps({
            "items": [
                {"title": "X", "description": "", "type": "weird_type"},
            ],
        })
        items, err = _parse_response(raw)
        assert err is None
        assert len(items) == 1
        assert items[0].type == "feature"  # fallback

    def test_missing_title_skipped(self):
        raw = json.dumps({
            "items": [
                {"title": "Valid", "description": "", "type": "feature"},
                {"description": "no title", "type": "feature"},  # title 없음 — 건너뜀
                {"title": "Also Valid", "description": "", "type": "feature"},
            ],
        })
        items, err = _parse_response(raw)
        assert err is None
        assert len(items) == 2
        assert items[0].title == "Valid"
        assert items[1].title == "Also Valid"

    def test_with_markdown_wrapper(self):
        """LLM이 ```json...```으로 감싸도 파싱 OK."""
        raw = '```json\n' + json.dumps({
            "items": [{"title": "X", "description": "", "type": "setup"}],
        }) + '\n```'
        items, err = _parse_response(raw)
        assert err is None
        assert len(items) == 1

    def test_finds_json_inside_text(self):
        """앞뒤에 텍스트가 있어도 JSON 블록 추출."""
        raw = '여기 결과입니다:\n\n{"items": [{"title": "X", "description": "", "type": "setup"}]}\n\n끝!'
        items, err = _parse_response(raw)
        assert err is None
        assert len(items) == 1

    def test_items_not_a_list(self):
        raw = json.dumps({"items": "not a list"})
        items, err = _parse_response(raw)
        assert items == []
        assert err is not None
        assert "list" in err

    def test_no_items_key(self):
        raw = json.dumps({"foo": "bar"})
        items, err = _parse_response(raw)
        assert items == []
        assert err is not None

    def test_empty_items_array(self):
        raw = json.dumps({"items": []})
        items, err = _parse_response(raw)
        assert items == []
        assert err is not None
        assert "비어" in err

    def test_all_items_invalid(self):
        """모든 항목에 title이 없으면 에러."""
        raw = json.dumps({
            "items": [
                {"description": "no title 1"},
                {"description": "no title 2"},
            ],
        })
        items, err = _parse_response(raw)
        assert items == []
        assert err is not None

    def test_estimated_files_not_list(self):
        """estimated_files가 list가 아니면 빈 리스트."""
        raw = json.dumps({
            "items": [
                {
                    "title": "X",
                    "description": "",
                    "type": "setup",
                    "estimated_files": "package.json",  # str — 무시되어야
                },
            ],
        })
        items, err = _parse_response(raw)
        assert err is None
        assert len(items) == 1
        assert items[0].estimated_files == []


# ---------------------------------------------------------------------------
# 공개 API — generate_todo_list (LLM mock)
# ---------------------------------------------------------------------------

class TestGenerateTodoList:
    """공개 API. LLM 호출은 mock."""

    def test_empty_raw_input(self):
        result = generate_todo_list("", None)
        assert isinstance(result, TodoListResult)
        assert not result.ok
        assert result.error is not None
        assert "비어" in result.error

    def test_only_whitespace(self):
        result = generate_todo_list("   \n\t  ", None)
        assert not result.ok

    @patch("src.app_dev.todo_planner.call_llm")
    def test_llm_returns_none(self, mock_llm):
        mock_llm.return_value = None
        result = generate_todo_list("RoomCrafting 만들어줘", None)
        assert not result.ok
        assert "LLM 호출 실패" in result.error

    @patch("src.app_dev.todo_planner.call_llm")
    def test_successful_call(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "items": [
                {"title": "셋업", "description": "...", "type": "setup"},
                {"title": "방 입력", "description": "...", "type": "feature"},
                {"title": "Rule Engine", "description": "...", "type": "engine"},
            ],
        })

        result = generate_todo_list(
            raw_input="RoomCrafting v1을 만들어줘",
            referenced_context={
                "files": [
                    {"filename": "CLAUDE.md", "content": "규칙들..."},
                ],
            },
        )

        assert result.ok
        assert len(result.items) == 3
        assert result.error is None
        # ID 순차 부여 확인
        assert result.items[0].id == "todo-1"
        assert result.items[2].id == "todo-3"

    @patch("src.app_dev.todo_planner.call_llm")
    def test_llm_returns_invalid_json(self, mock_llm):
        mock_llm.return_value = "I am not JSON."
        result = generate_todo_list("X", None)
        assert not result.ok
        assert "JSON" in result.error
        # 디버깅용 raw_response 보존
        assert result.raw_response == "I am not JSON."

    @patch("src.app_dev.todo_planner.call_llm")
    def test_call_llm_receives_referenced_context(self, mock_llm):
        """LLM 프롬프트에 referenced_context 파일 내용이 포함되는지 확인."""
        mock_llm.return_value = json.dumps({
            "items": [{"title": "X", "description": "", "type": "setup"}],
        })

        ctx = {
            "files": [
                {"filename": "MY_SPEC.md", "content": "DISTINCTIVE_MARKER_12345"},
            ],
        }
        generate_todo_list("test request", ctx)

        # call_llm이 받은 첫 인자(prompt)에 우리 마커가 들어있는지
        called_prompt = mock_llm.call_args[0][0]
        assert "DISTINCTIVE_MARKER_12345" in called_prompt
        assert "MY_SPEC.md" in called_prompt
        assert "test request" in called_prompt

    @patch("src.app_dev.todo_planner.call_llm")
    def test_works_without_referenced_context(self, mock_llm):
        """referenced_context 없어도 동작 (LLM에는 '없음' 표시)."""
        mock_llm.return_value = json.dumps({
            "items": [{"title": "X", "description": "", "type": "setup"}],
        })
        result = generate_todo_list("simple request", None)
        assert result.ok
        # call_llm이 받은 prompt에 "없음" 포함
        called_prompt = mock_llm.call_args[0][0]
        assert "없음" in called_prompt


# ---------------------------------------------------------------------------
# 데이터클래스 직렬화
# ---------------------------------------------------------------------------

class TestSerialization:
    """to_dict() 메서드."""

    def test_todo_item_to_dict(self):
        item = TodoItem(
            id="todo-1",
            title="X",
            description="desc",
            type="setup",
            estimated_files=["a.py"],
            status="pending",
        )
        d = item.to_dict()
        assert d == {
            "id": "todo-1",
            "title": "X",
            "description": "desc",
            "type": "setup",
            "estimated_files": ["a.py"],
            "status": "pending",
        }

    def test_todo_list_result_to_dict(self):
        result = TodoListResult(
            items=[
                TodoItem(id="todo-1", title="A", description="", type="setup"),
            ],
        )
        d = result.to_dict()
        assert "items" in d
        assert len(d["items"]) == 1
        assert d["error"] is None
        # raw_response는 to_dict에서 제외
        assert "raw_response" not in d


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

class TestConstants:
    def test_valid_types_set(self):
        # 핵심 타입 모두 포함
        assert "setup" in VALID_TODO_TYPES
        assert "feature" in VALID_TODO_TYPES
        assert "engine" in VALID_TODO_TYPES
        assert "schema" in VALID_TODO_TYPES
        assert "integration" in VALID_TODO_TYPES
