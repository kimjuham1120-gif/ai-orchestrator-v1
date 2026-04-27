"""
src/app_dev/build_executor.py — Step 15 Phase A5-2

build_planner가 만든 단계들을 받아서 실제 코드(파일 단위)를 LLM으로 생성.

build_planner와 분리한 이유:
  - planner는 "계획 수립" (짧은 응답, 빠름)
  - executor는 "코드 작성" (긴 응답, 큰 비용)
  - Anthropic 캐싱으로 referenced_context 재사용 시 90% 할인

공개 API:
  execute_steps(todo, steps, referenced_context, prior_results=None) -> BuildOutput

응답 JSON:
  {
    "summary": "...",
    "files": [
      {
        "action": "create" | "modify",
        "path": "src/components/RoomInput.tsx",
        "content": "전체 파일 내용",
        "reason": "이 파일이 왜 필요한지"
      }
    ],
    "notes": "운영자에게 알릴 사항 (선택)"
  }

설계 원칙:
  - modify도 전체 파일 내용 반환 (단순함 우선)
  - referenced_context의 규칙·제약 강제 준수
  - prior_results로 누적 컨텍스트
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

BUILD_EXECUTOR_MODEL = os.environ.get(
    "BUILD_EXECUTOR_MODEL",
    "anthropic/claude-sonnet-4-6",
)

try:
    BUILD_EXECUTOR_TIMEOUT = float(os.environ.get("BUILD_EXECUTOR_TIMEOUT", "180.0"))
except (ValueError, TypeError):
    BUILD_EXECUTOR_TIMEOUT = 180.0


VALID_ACTIONS = {"create", "modify"}


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

@dataclass
class FileSpec:
    """한 파일의 변경 사양."""
    action: str
    path: str
    content: str
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "path": self.path,
            "content": self.content,
            "reason": self.reason,
        }


@dataclass
class BuildOutput:
    """build_executor 호출 결과."""
    summary: str = ""
    files: List[FileSpec] = field(default_factory=list)
    notes: str = ""
    error: Optional[str] = None
    raw_response: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "files": [f.to_dict() for f in self.files],
            "notes": self.notes,
            "error": self.error,
        }

    @property
    def ok(self) -> bool:
        return self.error is None and len(self.files) > 0


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
당신은 점진적 앱개발의 코드 작성자다.
한 Todo와 그 단계 계획을 받아서 **실제 코드를 파일 단위로 작성**한다.

## 원칙
1. **이번 Todo와 단계만** 다룬다. 다른 Todo의 일은 손대지 않는다.
2. **참조 문서를 무조건 따른다**. CLAUDE.md, 기획문서에 명시된 규칙·기준값·제약은 절대 어기지 않는다.
3. **이전 Todo 결과와 일관성**. prior_results의 파일·구조와 충돌하지 않도록.
4. **완전한 파일 내용**. modify도 전체 파일을 반환 (부분이 아님).
5. **상대 경로**. 절대 경로 X (예: `src/components/RoomInput.tsx`).
6. **각 파일에 reason 명시**. 왜 만들거나 수정하는지.

## 출력 형식 — JSON만
```
{
  "summary": "이번 빌드의 한 줄 요약 (예: 'Vite + React 셋업 완료')",
  "files": [
    {
      "action": "create",
      "path": "src/types/room.ts",
      "content": "export type Room = {\\n  width: number;\\n  height: number;\\n};\\n",
      "reason": "방 정보를 cm 단위로 저장하는 타입 정의"
    },
    {
      "action": "modify",
      "path": "src/App.tsx",
      "content": "(전체 파일 내용)",
      "reason": "방 입력 화면을 메인에 연결"
    }
  ],
  "notes": "(선택) 운영자에게 알릴 사항"
}
```

마크다운 코드 블록(```) 없이 JSON 객체만 출력.
"""


_USER_PROMPT_TEMPLATE = """\
## 이번 작업할 Todo
ID: {todo_id}
제목: {todo_title}
설명: {todo_description}
타입: {todo_type}

## 단계 계획 (build_planner가 작성)
{steps_section}

## 첨부 기획문서 묶음 ({n_files}개)

{files_section}

{prior_section}

---

위 단계 계획을 모두 완수하는 실제 파일들을 JSON으로 출력하라.
참조 문서의 규칙을 절대 어기지 마라.
"""


# ---------------------------------------------------------------------------
# 헬퍼 — 컨텍스트 포맷
# ---------------------------------------------------------------------------

def _format_steps_for_prompt(steps: Optional[List[dict]]) -> str:
    """build_planner가 만든 steps를 텍스트로 포맷."""
    if not steps:
        return "(단계 계획 없음)"

    parts = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        order = s.get("order", "?")
        desc = s.get("description", "")
        files = s.get("file_hint") or []
        files_str = ", ".join(files) if files else "(미정)"
        parts.append(f"{order}. {desc}\n   추정 파일: {files_str}")

    return "\n".join(parts) if parts else "(단계 계획 없음)"


def _format_files_for_prompt(referenced_context: Optional[dict]) -> tuple[str, int]:
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


def _parse_response(raw: str) -> tuple[str, List[FileSpec], str, Optional[str]]:
    """
    LLM 응답 → (summary, files, notes, error).
    """
    if not raw or not raw.strip():
        return "", [], "", "LLM 응답이 비어있음"

    cleaned = _strip_json_wrapper(raw)

    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # 본문 안 { ... } 추출 (관대한 파싱)
        # files 안에 content가 길고 json 특수문자 포함될 수 있어 DOTALL 필수
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
            except json.JSONDecodeError:
                return "", [], "", f"JSON 파싱 실패: {e}"
        else:
            return "", [], "", f"JSON 파싱 실패: {e}"

    if not isinstance(obj, dict):
        return "", [], "", "응답이 dict 형식이 아님"

    summary = (obj.get("summary") or "").strip()
    notes = (obj.get("notes") or "").strip()

    raw_files = obj.get("files")
    if not isinstance(raw_files, list):
        return summary, [], notes, "files 키가 list 형식이 아님"

    if len(raw_files) == 0:
        return summary, [], notes, "files 배열이 비어있음"

    files: List[FileSpec] = []
    for raw_file in raw_files:
        if not isinstance(raw_file, dict):
            continue

        action = (raw_file.get("action") or "").strip().lower()
        if action not in VALID_ACTIONS:
            action = "create"  # fallback (보수적: 파일 만들기)

        path = (raw_file.get("path") or "").strip()
        if not path:
            continue  # path 없으면 건너뜀

        # 절대 경로는 거부 (보안 + 의도 위반)
        if path.startswith("/") or (len(path) >= 2 and path[1] == ":"):
            continue

        content = raw_file.get("content")
        if content is None:
            continue
        if not isinstance(content, str):
            content = str(content)

        reason = (raw_file.get("reason") or "").strip()

        files.append(FileSpec(
            action=action,
            path=path,
            content=content,
            reason=reason,
        ))

    if not files:
        return summary, [], notes, "유효한 파일이 하나도 추출되지 않음"

    return summary, files, notes, None


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def execute_steps(
    todo: dict,
    steps: List[dict],
    referenced_context: Optional[dict] = None,
    prior_results: Optional[List[dict]] = None,
) -> BuildOutput:
    """
    build_planner가 만든 단계들을 받아 실제 파일 코드를 LLM으로 생성.

    Args:
      todo: TodoItem.to_dict()
      steps: build_planner의 StepPlanResult.steps (각 PlanStep.to_dict())
      referenced_context: 업로드된 기획문서 묶음 (선택)
      prior_results: 이전 완료된 Todo들의 빌드 결과 (선택)

    Returns:
      BuildOutput — 성공 시 files 1개 이상, 실패 시 error.
    """
    if not isinstance(todo, dict):
        return BuildOutput(error="todo가 dict 형식이 아님")

    todo_title = (todo.get("title") or "").strip()
    if not todo_title:
        return BuildOutput(error="todo에 title이 없음")

    if not steps:
        return BuildOutput(error="steps가 비어있음 (build_planner 결과 필요)")

    # 프롬프트 조립
    files_section, n_files = _format_files_for_prompt(referenced_context)
    prior_section = _format_prior_results(prior_results)
    steps_section = _format_steps_for_prompt(steps)

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        todo_id=todo.get("id", "?"),
        todo_title=todo_title,
        todo_description=(todo.get("description") or "").strip() or "(설명 없음)",
        todo_type=todo.get("type", "feature"),
        steps_section=steps_section,
        n_files=n_files,
        files_section=files_section,
        prior_section=prior_section,
    )

    full_prompt = f"{_SYSTEM_PROMPT}\n\n{user_prompt}"

    raw_response = call_llm(full_prompt, BUILD_EXECUTOR_MODEL, BUILD_EXECUTOR_TIMEOUT)

    if raw_response is None:
        return BuildOutput(
            error="LLM 호출 실패 (API 키 없음 또는 네트워크 오류)",
        )

    summary, files, notes, parse_error = _parse_response(raw_response)
    if parse_error:
        return BuildOutput(
            summary=summary,
            notes=notes,
            error=parse_error,
            raw_response=raw_response,
        )

    return BuildOutput(
        summary=summary,
        files=files,
        notes=notes,
    )
