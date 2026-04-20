"""
Builder Service.

real 경로: OPENROUTER_API_KEY 있으면 OpenRouter 호출
fake 경로: API key 없으면 stub output 반환
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import httpx

from src.builder.builder_config import (
    get_builder_model, get_verbosity, _OPENROUTER_URL
)
from src.builder.builder_schema import BuilderResult, BUILDER_STATUS_CREATED


def _fake_output(plan: list[dict]) -> list[dict]:
    if plan:
        return [{"step": s["step"], "action": f"{s['description']} — stub 구현 완료"} for s in plan]
    return [
        {"step": 1, "action": "src/auth.py 수정 — 버그 수정 완료"},
        {"step": 2, "action": "tests/test_auth.py 추가 — 테스트 verify 완료"},
    ]


def _parse_output(text: str) -> list[dict]:
    steps = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if line[0].isdigit() and ". " in line:
            action = line.split(". ", 1)[1].strip()
        else:
            action = line
        if action:
            steps.append({"step": i, "action": action})
    return steps


def run_builder(
    raw_input: str,
    task_type: str,
    plan: list[dict],
) -> Tuple[BuilderResult, Optional[str]]:
    api_key = os.environ.get("OPENROUTER_API_KEY")

    if not api_key:
        return BuilderResult(
            builder_output=_fake_output(plan),
            builder_status=BUILDER_STATUS_CREATED,
        ), None

    model = get_builder_model()
    verbosity = get_verbosity()
    plan_text = "\n".join(
        f"{s['step']}. {s['description']}" for s in plan
    ) if plan else "(없음)"

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
                {
                    "role": "user",
                    "content": (
                        f"task_type: {task_type}\n"
                        f"goal: {raw_input}\n\n"
                        f"실행 계획:\n{plan_text}\n\n"
                        "각 단계별 구체적인 실행 내역을 번호 목록으로 작성하세요."
                    ),
                }
            ],
            "verbosity": verbosity,
        },
        timeout=30.0,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    output = _parse_output(content) or _fake_output(plan)
    return BuilderResult(
        builder_output=output,
        builder_status=BUILDER_STATUS_CREATED,
    ), model
