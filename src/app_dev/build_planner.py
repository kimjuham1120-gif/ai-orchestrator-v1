"""
src/app_dev/build_planner.py — Step 15 Phase A5-1

한 Todo 항목을 받아서 "이번 단위에서 무엇을 어떤 단계로 할 것인가"를
세부 계획으로 LLM에 요청.

build_executor와 분리한 이유:
  - planner는 "계획 수립" 단계 (낮은 effort, 짧은 응답)
  - executor는 "코드 작성" 단계 (높은 effort, 긴 응답)
  - Anthropic 캐싱으로 referenced_context 재사용 시 두 번째 호출 90% 할인

공개 API:
  plan_todo_steps(todo, referenced_context, prior_results=None) -> StepPlanResult

설계 원칙:
  - JSON 응답 강제
  - 한 Todo는 보통 2~5단계로 분해 (너무 많으면 오버킬)
  - file_hint는 추정만 — 실제 파일 결정은 build_executor가 함
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.utils.llm_utils import call_llm


# ---------------------------------------------------------------------------
# 모델 / 타임아웃
# ---------------------------------------------------------------------------

BUILD_PLANNER_MODEL = os.environ.get(
    "BUILD_PLANNER_MODEL",
    "anthropic/claude-sonnet-4-6",
)

try:
    BUILD_PLANNER_TIMEOUT = float(os.environ.get("BUILD_PLANNER_TIMEOUT", "60.0"))
except (ValueError, TypeError):
    BUILD_PLANNER_TIMEOUT = 60.0


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

@dataclass
class PlanStep:
    """한 단계."""
    order: int
    description: str
    file_hint: List[str] = field(default_factory=list)  # 추정 파일

    def to_dict(self) -> dict:
        return {
            "order": self.order,
            "description": self.description,
            "file_hint": self.file_hint,
        }


@dataclass
class StepPlanResult:
    """build_planner 호출 결과."""
    summary: str = ""
    steps: List[PlanStep] = field(default_factory=list)
    error: Optional[str] = None
    raw_response: Optional[str] = None  # 디버깅용

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "steps": [s.to_dict() for s in self.steps],
            "error": self.error,
        }

    @property
    def ok(self) -> bool:
        return self.error is None and len(self.steps) > 0


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
당신은 점진적 앱개발의 단계 플래너다.
한 작업 단위(Todo)를 받아서, 그 단위 안에서 어떤 순서로 진행할지를 2~5개 단계로 분해한다.

## 원칙
1. **이번 Todo만** 다룬다. 다른 Todo의 일은 건드리지 않는다.
2. **참조 문서를 따른다**. CLAUDE.md, 기획문서에 명시된 규칙·기준값·제약을 무조건 준수.
3. **2~5개 단계**로 분해. 각 단계는 한 줄 ~ 한 두 문장 설명.
4. **file_hint** — 어떤 파일이 만들어지거나 수정될지 추정 (실제는 다음 단계에서 결정).

## 출력 형식 — JSON만
```
{
  "summary": "이번 Todo의 한 줄 요약",
  "steps": [
    {
      "order": 1,
      "description": "구체적인 단계 설명",
      "file_hint": ["src/auth/login.py", "src/auth/types.ts"]
    },
    {
      "order": 2,
      "description": "...",
      "file_hint": ["..."]
    }
  ]
}
```

마크다운 코드 블록(```)이나 설명 텍스트 없이 JSON 객체만 출력.
"""


_USER_PROMPT_TEMPLATE = """\
## 이번 작업할 Todo
ID: {todo_id}
제목: {todo_title}
설명: {todo_description}
타입: {todo_type}
예상 파일: {todo_files}

## 첨부 기획문서 묶음 ({n_files}개)

{files_section}

{prior_section}

---

위 Todo를 수행하기 위한 단계 2~5개를 JSON으로 출력하라.
"""


# ---------------------------------------------------------------------------
# 헬퍼 — 컨텍스트 포맷
# ---------------------------------------------------------------------------

def _format_files_for_prompt(referenced_context: Optional[dict]) -> tuple[str, int]:
    """referenced_context의 파일들을 LLM 프롬프트로 포맷."""
    if not referenced_context or not isinstance(referenced_context, dict):
        return "(첨부 파일 없음)", 0

    files = referenced_context.get("files") or []
    if not files:
        return "(첨부 파일 없음)", 0

    parts = []
    for f in files:
        filename = f.get("filename", "(unnamed)")
        content = f.get("content", "")
        if not content:
            continue
        parts.append(f"### {filename}\n{content}")

    return "\n\n---\n\n".join(parts), len(parts)


def _format_prior_results(prior_results: Optional[List[dict]]) -> str:
    """이전 Todo들의 빌드 결과를 누적 컨텍스트로 포맷."""
    if not prior_results:
        return ""

    parts = ["## 이전 완료된 Todo 결과 (누적 컨텍스트)"]
    for idx, pr in enumerate(prior_results, 1):
        title = pr.get("title", "(unknown)")
        summary = pr.get("summary", "")
        files = pr.get("files", [])
        files_str = ", ".join(f.get("path", "") for f in files if f.get("path"))

        parts.append(f"### Todo {idx}: {title}")
        if summary:
            parts.append(f"  요약: {summary}")
        if files_str:
            parts.append(f"  생성/수정 파일: {files_str}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# JSON 파싱 (관대)
# ---------------------------------------------------------------------------

def _strip_json_wrapper(text: str) -> str:
    if not text:
        return text
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*\n", "", cleaned)
    cleaned = re.sub(r"\n```\s*$", "", cleaned)
    return cleaned.strip()


def _parse_response(raw: str) -> tuple[str, List[PlanStep], Optional[str]]:
    """LLM 응답 → (summary, steps, error)."""
    if not raw or not raw.strip():
        return "", [], "LLM 응답이 비어있음"

    cleaned = _strip_json_wrapper(raw)

    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # 본문 안에서 { ... } 추출 시도
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
            except json.JSONDecodeError:
                return "", [], f"JSON 파싱 실패: {e}"
        else:
            return "", [], f"JSON 파싱 실패: {e}"

    if not isinstance(obj, dict):
        return "", [], "응답이 dict 형식이 아님"

    summary = (obj.get("summary") or "").strip()

    raw_steps = obj.get("steps")
    if not isinstance(raw_steps, list):
        return summary, [], "steps 키가 list 형식이 아님"

    if len(raw_steps) == 0:
        return summary, [], "steps 배열이 비어있음"

    steps: List[PlanStep] = []
    for idx, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            continue

        description = (raw_step.get("description") or "").strip()
        if not description:
            continue

        order = raw_step.get("order")
        if not isinstance(order, int) or order < 1:
            order = idx + 1  # fallback

        raw_files = raw_step.get("file_hint") or []
        if isinstance(raw_files, list):
            file_hint = [str(f).strip() for f in raw_files if f]
        else:
            file_hint = []

        steps.append(PlanStep(
            order=order,
            description=description,
            file_hint=file_hint,
        ))

    if not steps:
        return summary, [], "유효한 단계가 하나도 추출되지 않음"

    # 정렬 안전화 (order 기준)
    steps.sort(key=lambda s: s.order)

    return summary, steps, None


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def plan_todo_steps(
    todo: dict,
    referenced_context: Optional[dict] = None,
    prior_results: Optional[List[dict]] = None,
) -> StepPlanResult:
    """
    한 Todo의 세부 단계 계획을 LLM으로 생성.

    Args:
      todo: TodoItem.to_dict() (id, title, description, type, estimated_files)
      referenced_context: 업로드된 기획문서 묶음 (선택)
      prior_results: 이전 완료된 Todo들의 빌드 결과 (선택)

    Returns:
      StepPlanResult — 성공 시 steps 2~5개, 실패 시 error.
    """
    if not isinstance(todo, dict):
        return StepPlanResult(error="todo가 dict 형식이 아님")

    todo_title = (todo.get("title") or "").strip()
    if not todo_title:
        return StepPlanResult(error="todo에 title이 없음")

    # 프롬프트 조립
    files_section, n_files = _format_files_for_prompt(referenced_context)
    prior_section = _format_prior_results(prior_results)

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        todo_id=todo.get("id", "?"),
        todo_title=todo_title,
        todo_description=(todo.get("description") or "").strip() or "(설명 없음)",
        todo_type=todo.get("type", "feature"),
        todo_files=", ".join(todo.get("estimated_files") or []) or "(미정)",
        n_files=n_files,
        files_section=files_section,
        prior_section=prior_section,
    )

    full_prompt = f"{_SYSTEM_PROMPT}\n\n{user_prompt}"

    raw_response = call_llm(full_prompt, BUILD_PLANNER_MODEL, BUILD_PLANNER_TIMEOUT)

    if raw_response is None:
        return StepPlanResult(
            error="LLM 호출 실패 (API 키 없음 또는 네트워크 오류)",
        )

    summary, steps, parse_error = _parse_response(raw_response)
    if parse_error:
        return StepPlanResult(
            summary=summary,
            error=parse_error,
            raw_response=raw_response,
        )

    return StepPlanResult(summary=summary, steps=steps)
