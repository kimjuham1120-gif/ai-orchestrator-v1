"""
Initial Document Generator.

real 경로: OPENROUTER_API_KEY 있으면 OpenRouter 호출
fake 경로: API key 없으면 구조화된 stub 문서 반환

반환: InitialDocument (dataclass)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

def _get_openrouter_url() -> str:
    base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    return f"{base.rstrip('/')}/chat/completions"

_OPENROUTER_URL = _get_openrouter_url()


@dataclass
class DocumentSection:
    heading: str
    content: str

    def to_dict(self) -> dict:
        return {"heading": self.heading, "content": self.content}


@dataclass
class InitialDocument:
    title: str
    sections: list[DocumentSection] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "sections": [s.to_dict() for s in self.sections],
        }


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------

_SYSTEM = """당신은 소프트웨어 프로젝트 문서 작성 전문가입니다.
요청을 받으면 아래 형식으로 프로젝트 문서를 작성하십시오.

형식 (각 섹션을 ## 헤딩으로 구분):
## 목적
## 범위
## 제약 조건
## 수행 방법
## 완료 기준

간결하고 명확하게 작성하십시오."""


def _parse_sections(text: str) -> list[DocumentSection]:
    sections = []
    current_heading = ""
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_heading:
                sections.append(DocumentSection(
                    heading=current_heading,
                    content="\n".join(current_lines).strip(),
                ))
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading:
        sections.append(DocumentSection(
            heading=current_heading,
            content="\n".join(current_lines).strip(),
        ))

    return sections


# ---------------------------------------------------------------------------
# Fake (stub)
# ---------------------------------------------------------------------------

def _fake_document(goal: str, task_type: str) -> InitialDocument:
    return InitialDocument(
        title=f"[{task_type}] {goal[:60]}",
        sections=[
            DocumentSection("목적", f"{goal}을 달성하기 위한 문서."),
            DocumentSection("범위", "변경 대상 모듈 및 파일 범위."),
            DocumentSection("제약 조건", "scope 이탈 금지. 기존 인터페이스 유지."),
            DocumentSection("수행 방법", "1. 문제 분석\n2. 수정 구현\n3. 테스트 검증"),
            DocumentSection("완료 기준", "모든 테스트 통과. 리뷰 승인."),
        ],
    )


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def generate_initial_document(
    goal: str,
    task_type: str,
    evidence_bundle: Optional[dict] = None,
) -> InitialDocument:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_DOC_MODEL", "openai/gpt-4o-mini")

    if not api_key:
        return _fake_document(goal, task_type)

    context = ""
    if evidence_bundle:
        claims = evidence_bundle.get("claims", [])[:3]
        if claims:
            context = "\n참고 정보:\n" + "\n".join(
                f"- {c['text']}" for c in claims
            )

    user_prompt = (
        f"task_type: {task_type}\n"
        f"goal: {goal}"
        f"{context}"
    )

    resp = httpx.post(
        _OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://ai-orchestrator-v1",
            "X-Title": "ai-orchestrator-v1",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=30.0,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    sections = _parse_sections(content)

    if len(sections) < 3:
        # 파싱 실패 시 단일 섹션
        sections = [DocumentSection("내용", content)]

    return InitialDocument(
        title=f"[{task_type}] {goal[:60]}",
        sections=sections,
    )
