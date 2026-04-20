"""
Planner Service.

real 경로: OPENROUTER_API_KEY 있으면 OpenRouter 호출
fake 경로: API key 없으면 stub plan 반환
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import httpx

from src.planner.planner_config import (
    get_planner_model, get_reasoning_effort, _OPENROUTER_URL
)
from src.planner.planner_schema import PlanResult, PLAN_STATUS_CREATED


_FAKE_PLAN = [
    {"step": 1, "description": "문제 파악 및 재현"},
    {"step": 2, "description": "수정 대상 파일/함수 확인"},
    {"step": 3, "description": "범위 고정 후 구현"},
    {"step": 4, "description": "테스트 작성 및 검증"},
]


def _parse_plan(text: str) -> list[dict]:
    steps = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        # "1. xxx" 형태 파싱
        if line[0].isdigit() and ". " in line:
            desc = line.split(". ", 1)[1].strip()
        else:
            desc = line
        if desc:
            steps.append({"step": i, "description": desc})
    return steps or _FAKE_PLAN


def run_planner(
    raw_input: str,
    task_type: str,
) -> Tuple[PlanResult, Optional[str]]:
    api_key = os.environ.get("OPENROUTER_API_KEY")

    if not api_key:
        return PlanResult(plan=_FAKE_PLAN, plan_status=PLAN_STATUS_CREATED), None

    model = get_planner_model()
    effort = get_reasoning_effort()

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
                        "위 목표를 달성하기 위한 실행 계획을 번호 목록으로 작성하세요. "
                        "각 단계는 한 줄로 간결하게."
                    ),
                }
            ],
            "reasoning": {"effort": effort},
        },
        timeout=30.0,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    plan = _parse_plan(content)
    return PlanResult(plan=plan, plan_status=PLAN_STATUS_CREATED), model
