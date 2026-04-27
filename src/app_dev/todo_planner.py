"""
src/app_dev/todo_planner.py — Step 15 Phase A3

referenced_context (업로드된 기획문서 묶음)를 LLM에 통째로 던져서
N개 작업 단위(Todo)로 분해.

공개 API:
  generate_todo_list(raw_input, referenced_context) -> TodoListResult

설계 원칙:
  - 한 작업 단위 = 하나의 화면 또는 하나의 핵심 동작
  - 30~60분 단위 (운영자가 UI에서 30초 안에 확인 가능한 크기)
  - 의존 순서대로 정렬 (셋업 → 타입 → 화면 → 엔진 → 통합)

LLM 응답은 JSON. 파싱 실패 시 fallback 처리.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.utils.llm_utils import call_llm


# ---------------------------------------------------------------------------
# 모델 / 타임아웃 설정
# ---------------------------------------------------------------------------

PLANNER_MODEL = os.environ.get(
    "TODO_PLANNER_MODEL",
    "anthropic/claude-sonnet-4-6",  # 기본은 Anthropic 캐싱 활용
)

try:
    PLANNER_TIMEOUT = float(os.environ.get("TODO_PLANNER_TIMEOUT", "120.0"))
except (ValueError, TypeError):
    PLANNER_TIMEOUT = 120.0


# 작업 단위 타입 (validator용)
VALID_TODO_TYPES = {
    "setup", "schema", "engine", "feature",
    "integration", "fix", "refactor",
}


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

@dataclass
class TodoItem:
    """단일 작업 단위."""
    id: str                                    # "todo-1", "todo-2", ...
    title: str                                 # 짧은 제목
    description: str                           # 한 줄 ~ 몇 줄
    type: str                                  # "setup" | "schema" | ...
    estimated_files: List[str] = field(default_factory=list)
    status: str = "pending"                    # "pending" | "in_progress" | "completed" | ...

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "type": self.type,
            "estimated_files": self.estimated_files,
            "status": self.status,
        }


@dataclass
class TodoListResult:
    """todo_planner 호출 결과."""
    items: List[TodoItem] = field(default_factory=list)
    error: Optional[str] = None
    raw_response: Optional[str] = None         # 디버깅용 원본 응답

    def to_dict(self) -> dict:
        return {
            "items": [t.to_dict() for t in self.items],
            "error": self.error,
        }

    @property
    def ok(self) -> bool:
        return self.error is None and len(self.items) > 0


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
당신은 점진적 앱개발 플래너다. 사용자의 기획 문서를 보고
앱을 30~60분 단위로 N개 작업으로 분해한다.

## 원칙
1. **한 작업 단위 = 하나의 화면 또는 하나의 핵심 동작**
   - 운영자가 UI에서 30초 안에 동작을 확인할 수 있는 크기
   - 너무 작지 않게: "한 줄 변경" 같은 미세한 작업 X
   - 너무 크지 않게: "전체 UI" 같은 통째 작업 X

2. **의존 순서대로 정렬**
   - 셋업 → 타입 정의 → 핵심 엔진 → UI → 통합 → 추적/저장
   - 앞 작업이 끝나야 뒷 작업이 가능한 순서

3. **각 작업에 type 부여**
   - setup       프로젝트 초기 셋업 (의존성, 설정)
   - schema      DB 스키마 / 타입 정의 (TypeScript 타입 등)
   - engine      순수 로직 (Rule Engine, Cost Engine 등)
   - feature     UI + 동작 (사용자가 화면에서 확인 가능)
   - integration 컴포넌트 연결 / 라우팅 / 상태 통합
   - fix         버그 수정
   - refactor    리팩토링 (점진 빌드에선 잘 안 함)

4. **estimated_files 명시**
   - 각 작업이 만들거나 수정할 파일을 추정해서 1~5개 나열
   - 절대 경로 X, 상대 경로만 (예: "src/components/RoomInput.tsx")

5. **N의 적정 범위는 7~15개**
   - 너무 적으면 한 단위가 너무 큼
   - 너무 많으면 운영자가 지침
   - 사용자 요청과 기획문서 분량에 맞춰 자연스럽게

## 출력 형식
**JSON 객체로만 응답한다.** 마크다운 코드 블록(`)이나 설명 텍스트 없이.

```
{
  "items": [
    {
      "title": "프로젝트 셋업 (Vite + React + TypeScript)",
      "description": "Vite + React 18 + TypeScript + Tailwind 환경 구성. 빈 메인 페이지 + dev 서버 동작 확인까지.",
      "type": "setup",
      "estimated_files": ["package.json", "vite.config.ts", "tsconfig.json", "src/main.tsx"]
    },
    {
      "title": "Room 타입 + 방 입력 화면",
      "description": "Room 타입 정의 (가로/세로/문/창문 — cm 단위). 방 입력 폼 UI. 직사각형만 허용.",
      "type": "feature",
      "estimated_files": ["src/types/room.ts", "src/components/RoomInput.tsx"]
    }
  ]
}
```

위 형식 그대로. 다른 키나 설명을 추가하지 마라.
"""


_USER_PROMPT_TEMPLATE = """\
## 원본 요청
{raw_input}

## 첨부된 기획문서 묶음 ({n_files}개 파일)

{files_section}

---

위 기획문서를 기반으로 30~60분 단위 작업 7~15개로 분해하라.
JSON으로만 응답하라.
"""


# ---------------------------------------------------------------------------
# referenced_context → 프롬프트 텍스트 변환
# ---------------------------------------------------------------------------

def _format_files_for_prompt(referenced_context: dict) -> tuple[str, int]:
    """
    referenced_context의 파일들을 LLM 프롬프트에 주입 가능한 텍스트로 포맷.

    Returns: (files_section_text, n_files)
    """
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


# ---------------------------------------------------------------------------
# JSON 응답 파싱 (관대하게)
# ---------------------------------------------------------------------------

def _strip_json_wrapper(text: str) -> str:
    """LLM이 ```json ... ``` 으로 감쌌으면 제거."""
    if not text:
        return text
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*\n", "", cleaned)
    cleaned = re.sub(r"\n```\s*$", "", cleaned)
    return cleaned.strip()


def _parse_response(raw: str) -> tuple[List[TodoItem], Optional[str]]:
    """
    LLM 응답 텍스트를 TodoItem 목록으로 파싱.

    Returns: (items, error_or_None)
    """
    if not raw or not raw.strip():
        return [], "LLM 응답이 비어있음"

    cleaned = _strip_json_wrapper(raw)

    # JSON 파싱 시도
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # JSON 파싱 실패 — 본문 안에서 { ... } 블록 찾기
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
            except json.JSONDecodeError:
                return [], f"JSON 파싱 실패: {e}"
        else:
            return [], f"JSON 파싱 실패: {e}"

    # 구조 검증
    if not isinstance(obj, dict):
        return [], "응답이 dict 형식이 아님"

    raw_items = obj.get("items")
    if not isinstance(raw_items, list):
        return [], "items 키가 list 형식이 아님"

    if len(raw_items) == 0:
        return [], "items 배열이 비어있음"

    # TodoItem으로 변환
    items: List[TodoItem] = []
    for idx, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            continue

        title = (raw_item.get("title") or "").strip()
        description = (raw_item.get("description") or "").strip()
        item_type = (raw_item.get("type") or "feature").strip().lower()

        if not title:
            continue  # 제목 없는 항목은 건너뜀

        # type 검증 (모르는 타입이면 "feature"로 fallback)
        if item_type not in VALID_TODO_TYPES:
            item_type = "feature"

        # estimated_files 검증
        raw_files = raw_item.get("estimated_files") or []
        if isinstance(raw_files, list):
            estimated_files = [str(f).strip() for f in raw_files if f]
        else:
            estimated_files = []

        items.append(TodoItem(
            id=f"todo-{idx + 1}",
            title=title,
            description=description,
            type=item_type,
            estimated_files=estimated_files,
            status="pending",
        ))

    if not items:
        return [], "유효한 항목이 하나도 추출되지 않음"

    return items, None


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def generate_todo_list(
    raw_input: str,
    referenced_context: Optional[dict] = None,
) -> TodoListResult:
    """
    referenced_context를 LLM에 던져서 N개 작업 단위로 분해.

    Args:
      raw_input: 사용자 원본 요청 (예: "RoomCrafting v1 만들어줘")
      referenced_context: 업로드된 기획문서 묶음 (선택)

    Returns:
      TodoListResult — 성공 시 items 7~15개, 실패 시 error 채워짐.
    """
    # 입력 검증
    text = (raw_input or "").strip()
    if not text:
        return TodoListResult(error="raw_input이 비어있음")

    # 파일 섹션 준비
    files_section, n_files = _format_files_for_prompt(referenced_context)

    # 프롬프트 조립
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        raw_input=text,
        n_files=n_files,
        files_section=files_section,
    )

    full_prompt = f"{_SYSTEM_PROMPT}\n\n{user_prompt}"

    # LLM 호출 (캐싱 자동 — 긴 referenced_context는 캐시 적중 효과 큼)
    raw_response = call_llm(full_prompt, PLANNER_MODEL, PLANNER_TIMEOUT)

    if raw_response is None:
        return TodoListResult(
            error="LLM 호출 실패 (API 키 없음 또는 네트워크 오류)",
        )

    # 파싱
    items, parse_error = _parse_response(raw_response)
    if parse_error:
        return TodoListResult(
            error=parse_error,
            raw_response=raw_response,  # 디버깅용
        )

    return TodoListResult(items=items)
