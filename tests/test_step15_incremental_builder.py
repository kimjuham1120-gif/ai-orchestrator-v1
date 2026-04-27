"""
tests/test_step15_incremental_builder.py — Step 15 A5-3

테스트 대상:
  - build_one_todo() 공개 API (planner/executor mock)
  - BuildResult 직렬화 + ok 판정 + summary/files 프로퍼티
  - build_result_to_prior_entry() 헬퍼

테스트 전략:
  - plan_todo_steps와 execute_steps를 mock하여 흐름 제어
  - 4가지 경로 모두 커버:
    1) 입력 검증 실패
    2) planner 실패
    3) executor 실패
    4) 둘 다 성공
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from src.app_dev.incremental_builder import (
    BuildResult,
    build_one_todo,
    build_result_to_prior_entry,
)
from src.app_dev.build_planner import StepPlanResult, PlanStep
from src.app_dev.build_executor import BuildOutput, FileSpec


# ---------------------------------------------------------------------------
# 헬퍼 — mock 결과 생성
# ---------------------------------------------------------------------------

def _ok_plan(summary="planner OK", n_steps=2) -> StepPlanResult:
    """성공한 planner 결과 가짜."""
    return StepPlanResult(
        summary=summary,
        steps=[
            PlanStep(order=i + 1, description=f"step {i+1}")
            for i in range(n_steps)
        ],
    )


def _fail_plan(error="planner 에러") -> StepPlanResult:
    return StepPlanResult(error=error)


def _ok_build(summary="build OK", n_files=2) -> BuildOutput:
    """성공한 executor 결과 가짜."""
    return BuildOutput(
        summary=summary,
        files=[
            FileSpec(action="create", path=f"src/file_{i}.py", content="x")
            for i in range(n_files)
        ],
    )


def _fail_build(error="executor 에러") -> BuildOutput:
    return BuildOutput(error=error)


# ---------------------------------------------------------------------------
# 입력 검증
# ---------------------------------------------------------------------------

class TestInputValidation:

    def test_todo_not_dict(self):
        result = build_one_todo("not a dict")
        assert not result.ok
        assert "dict" in result.error
        assert result.duration_ms >= 0

    def test_todo_no_title(self):
        result = build_one_todo({"id": "x"})
        assert not result.ok
        assert "title" in result.error

    def test_todo_empty_title(self):
        result = build_one_todo({"id": "x", "title": "   "})
        assert not result.ok
        assert "title" in result.error


# ---------------------------------------------------------------------------
# Planner 실패
# ---------------------------------------------------------------------------

class TestPlannerFailure:

    @patch("src.app_dev.incremental_builder.plan_todo_steps")
    @patch("src.app_dev.incremental_builder.execute_steps")
    def test_planner_fails_executor_not_called(self, mock_exec, mock_plan):
        mock_plan.return_value = _fail_plan("plan err")

        result = build_one_todo({"id": "t1", "title": "X"})

        assert not result.ok
        assert "build_planner 실패" in result.error
        assert "plan err" in result.error
        # plan 결과는 보존
        assert result.plan is not None
        # executor는 호출되지 않음
        mock_exec.assert_not_called()
        # build는 None
        assert result.build is None


# ---------------------------------------------------------------------------
# Executor 실패
# ---------------------------------------------------------------------------

class TestExecutorFailure:

    @patch("src.app_dev.incremental_builder.plan_todo_steps")
    @patch("src.app_dev.incremental_builder.execute_steps")
    def test_executor_fails_plan_preserved(self, mock_exec, mock_plan):
        mock_plan.return_value = _ok_plan("planner OK")
        mock_exec.return_value = _fail_build("exec err")

        result = build_one_todo({"id": "t1", "title": "X"})

        assert not result.ok
        assert "build_executor 실패" in result.error
        assert "exec err" in result.error
        # plan, build 둘 다 보존 (디버깅용)
        assert result.plan is not None
        assert result.plan.summary == "planner OK"
        assert result.build is not None
        assert result.build.error == "exec err"


# ---------------------------------------------------------------------------
# 성공 경로
# ---------------------------------------------------------------------------

class TestSuccessPath:

    @patch("src.app_dev.incremental_builder.plan_todo_steps")
    @patch("src.app_dev.incremental_builder.execute_steps")
    def test_both_succeed(self, mock_exec, mock_plan):
        mock_plan.return_value = _ok_plan(summary="셋업 계획", n_steps=3)
        mock_exec.return_value = _ok_build(summary="셋업 완료", n_files=4)

        todo = {"id": "todo-1", "title": "셋업"}
        result = build_one_todo(todo)

        assert result.ok
        assert result.error is None
        assert result.todo_id == "todo-1"
        # 둘 다 호출됨
        mock_plan.assert_called_once()
        mock_exec.assert_called_once()
        # 결과 검증
        assert result.plan is not None
        assert len(result.plan.steps) == 3
        assert result.build is not None
        assert len(result.build.files) == 4
        assert result.summary == "셋업 완료"  # build의 summary 우선
        assert len(result.files) == 4
        # duration 측정됨
        assert result.duration_ms >= 0

    @patch("src.app_dev.incremental_builder.plan_todo_steps")
    @patch("src.app_dev.incremental_builder.execute_steps")
    def test_planner_steps_passed_to_executor(self, mock_exec, mock_plan):
        """planner의 steps가 executor에 전달되는지 확인."""
        mock_plan.return_value = _ok_plan(n_steps=3)
        mock_exec.return_value = _ok_build()

        build_one_todo({"id": "t", "title": "X"})

        # executor 호출 시 steps 인자 확인
        call_kwargs = mock_exec.call_args[1]
        passed_steps = call_kwargs["steps"]
        assert isinstance(passed_steps, list)
        assert len(passed_steps) == 3
        # 각 step은 dict 형태 (PlanStep.to_dict())
        assert all("order" in s for s in passed_steps)
        assert all("description" in s for s in passed_steps)

    @patch("src.app_dev.incremental_builder.plan_todo_steps")
    @patch("src.app_dev.incremental_builder.execute_steps")
    def test_referenced_context_passed_to_both(self, mock_exec, mock_plan):
        mock_plan.return_value = _ok_plan()
        mock_exec.return_value = _ok_build()

        ctx = {"files": [{"filename": "spec.md", "content": "rules"}]}
        build_one_todo({"id": "t", "title": "X"}, referenced_context=ctx)

        # 둘 다에 전달되어야
        plan_kwargs = mock_plan.call_args[1]
        exec_kwargs = mock_exec.call_args[1]
        assert plan_kwargs["referenced_context"] == ctx
        assert exec_kwargs["referenced_context"] == ctx

    @patch("src.app_dev.incremental_builder.plan_todo_steps")
    @patch("src.app_dev.incremental_builder.execute_steps")
    def test_prior_results_passed_to_both(self, mock_exec, mock_plan):
        mock_plan.return_value = _ok_plan()
        mock_exec.return_value = _ok_build()

        prior = [{"title": "before", "summary": "...", "files": []}]
        build_one_todo({"id": "t", "title": "X"}, prior_results=prior)

        plan_kwargs = mock_plan.call_args[1]
        exec_kwargs = mock_exec.call_args[1]
        assert plan_kwargs["prior_results"] == prior
        assert exec_kwargs["prior_results"] == prior


# ---------------------------------------------------------------------------
# BuildResult 프로퍼티
# ---------------------------------------------------------------------------

class TestBuildResultProperties:

    def test_ok_requires_plan_and_build_both_ok(self):
        # 모두 None
        r = BuildResult()
        assert not r.ok

        # plan만
        r = BuildResult(plan=_ok_plan())
        assert not r.ok

        # 둘 다 + error
        r = BuildResult(plan=_ok_plan(), build=_ok_build(), error="x")
        assert not r.ok

        # 둘 다 OK
        r = BuildResult(plan=_ok_plan(), build=_ok_build())
        assert r.ok

        # plan 실패
        r = BuildResult(plan=_fail_plan(), build=_ok_build())
        assert not r.ok

        # build 실패
        r = BuildResult(plan=_ok_plan(), build=_fail_build())
        assert not r.ok

    def test_summary_prefers_build(self):
        r = BuildResult(
            plan=_ok_plan(summary="plan summary"),
            build=_ok_build(summary="build summary"),
        )
        assert r.summary == "build summary"

    def test_summary_falls_back_to_plan(self):
        r = BuildResult(plan=_ok_plan(summary="only plan"))
        assert r.summary == "only plan"

    def test_summary_empty_when_neither(self):
        assert BuildResult().summary == ""

    def test_files_property(self):
        r = BuildResult(build=_ok_build(n_files=3))
        assert len(r.files) == 3
        # dict 형태
        assert all("path" in f for f in r.files)

    def test_files_empty_when_no_build(self):
        assert BuildResult().files == []


# ---------------------------------------------------------------------------
# 직렬화
# ---------------------------------------------------------------------------

class TestSerialization:

    def test_to_dict_full(self):
        r = BuildResult(
            todo_id="todo-1",
            plan=_ok_plan(),
            build=_ok_build(),
            duration_ms=1234,
        )
        d = r.to_dict()
        assert d["todo_id"] == "todo-1"
        assert d["plan"] is not None
        assert d["build"] is not None
        assert d["duration_ms"] == 1234
        assert d["error"] is None

    def test_to_dict_with_error(self):
        r = BuildResult(error="something failed")
        d = r.to_dict()
        assert d["error"] == "something failed"
        assert d["plan"] is None
        assert d["build"] is None


# ---------------------------------------------------------------------------
# build_result_to_prior_entry
# ---------------------------------------------------------------------------

class TestPriorEntryHelper:

    def test_none_result(self):
        entry = build_result_to_prior_entry(None, "X")
        assert entry == {"title": "X", "summary": "", "files": []}

    def test_successful_result(self):
        r = BuildResult(
            plan=_ok_plan(),
            build=_ok_build(summary="셋업 완료", n_files=3),
        )
        entry = build_result_to_prior_entry(r, "프로젝트 셋업")
        assert entry["title"] == "프로젝트 셋업"
        assert entry["summary"] == "셋업 완료"
        assert len(entry["files"]) == 3
        # 각 file 항목은 path만
        assert all("path" in f for f in entry["files"])
        assert all(set(f.keys()) == {"path"} for f in entry["files"])

    def test_failed_result_no_files(self):
        r = BuildResult(plan=_fail_plan(), error="x")
        entry = build_result_to_prior_entry(r, "X")
        assert entry["title"] == "X"
        assert entry["summary"] == ""
        assert entry["files"] == []
