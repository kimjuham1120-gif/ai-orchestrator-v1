"""Planner 서비스 — OpenRouter LLM 호출 또는 fake 경로."""
from __future__ import annotations

import json
import httpx

from src.planner.planner_schema import (
    PlannerInput, PlannerOutput, PlanStep,
    PLAN_STATUS_CREATED, PLAN_STATUS_FAILED,
)
from src.planner.planner_prompt import PLANNER_SYSTEM_PROMPT, build_user_prompt
from src.planner.planner_config import (
    is_llm_ready, get_api_key, get_planner_model,
    get_planner_reasoning_effort, get_base_url, CHAT_PATH,
)


def _prepare_input(raw_input: str, task_type: str) -> PlannerInput:
    return PlannerInput(raw_input=raw_input.strip(), task_type=task_type.strip())


def _run_fake_planner(inp: PlannerInput) -> PlannerOutput:
    steps = [
        PlanStep(step=1, description="문제 입력 해석"),
        PlanStep(step=2, description="수정 대상 확인"),
        PlanStep(step=3, description="승인 전 범위 고정"),
    ]
    return PlannerOutput(plan=steps, plan_status=PLAN_STATUS_CREATED)


def _parse_llm_output(content: str) -> PlannerOutput:
    try:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(
                line for line in cleaned.splitlines()
                if not line.strip().startswith("```")
            ).strip()
        data = json.loads(cleaned)
        raw_steps = data.get("plan") or data.get("steps") or []
        if isinstance(raw_steps, list) and raw_steps:
            steps = []
            for i, item in enumerate(raw_steps, start=1):
                if isinstance(item, dict):
                    desc = item.get("description") or item.get("desc") or str(item)
                    step_num = item.get("step", i)
                else:
                    desc, step_num = str(item), i
                steps.append(PlanStep(step=step_num, description=desc.strip()))
            return PlannerOutput(plan=steps, plan_status=PLAN_STATUS_CREATED)
    except (json.JSONDecodeError, Exception):
        pass

    lines = [
        line.lstrip("0123456789.-) ").strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    lines = [l for l in lines if l]
    if lines:
        steps = [PlanStep(step=i, description=l) for i, l in enumerate(lines[:5], start=1)]
        return PlannerOutput(plan=steps, plan_status=PLAN_STATUS_CREATED)

    raise ValueError(f"planner LLM 응답 파싱 실패: {content[:200]!r}")


def _run_llm_planner(inp: PlannerInput) -> PlannerOutput:
    url = get_base_url() + CHAT_PATH
    payload = {
        "model": get_planner_model(),
        "messages": [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user",   "content": build_user_prompt(inp.raw_input, inp.task_type)},
        ],
        "reasoning": {"effort": get_planner_reasoning_effort()},
    }
    headers = {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type":  "application/json",
    }
    response = httpx.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _parse_llm_output(content)


def run_planner(raw_input: str, task_type: str) -> tuple[PlannerOutput, str | None]:
    """반환: (PlannerOutput, model_id | None)"""
    inp = _prepare_input(raw_input, task_type)
    if not is_llm_ready():
        return _run_fake_planner(inp), None
    return _run_llm_planner(inp), get_planner_model()
