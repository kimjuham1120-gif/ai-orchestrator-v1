"""Builder 서비스 — OpenRouter LLM 호출 또는 fake 경로."""
from __future__ import annotations

import json
import httpx

from src.builder.builder_schema import (
    BuilderInput, BuilderOutput, BuilderStep,
    BUILDER_STATUS_CREATED, BUILDER_STATUS_FAILED,
)
from src.builder.builder_prompt import BUILDER_SYSTEM_PROMPT, build_user_prompt
from src.builder.builder_config import (
    is_llm_ready, get_api_key, get_builder_model,
    get_builder_verbosity, get_base_url, CHAT_PATH,
)


def _prepare_input(raw_input: str, task_type: str, plan: list[dict]) -> BuilderInput:
    return BuilderInput(raw_input=raw_input.strip(), task_type=task_type.strip(), plan=plan)


def _run_fake_builder(inp: BuilderInput) -> BuilderOutput:
    steps = [
        BuilderStep(step=1, action="수정 후보 파일 확인"),
        BuilderStep(step=2, action="변경 포인트 초안 작성"),
        BuilderStep(step=3, action="테스트 포인트 정리"),
    ]
    return BuilderOutput(builder_output=steps, builder_status=BUILDER_STATUS_CREATED)


def _parse_llm_output(content: str) -> BuilderOutput:
    try:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(
                line for line in cleaned.splitlines()
                if not line.strip().startswith("```")
            ).strip()
        data = json.loads(cleaned)
        raw_steps = data.get("builder_output") or data.get("actions") or data.get("steps") or []
        if isinstance(raw_steps, list) and raw_steps:
            steps = []
            for i, item in enumerate(raw_steps, start=1):
                if isinstance(item, dict):
                    action = item.get("action") or item.get("description") or item.get("desc") or str(item)
                    step_num = item.get("step", i)
                else:
                    action, step_num = str(item), i
                steps.append(BuilderStep(step=step_num, action=action.strip()))
            return BuilderOutput(builder_output=steps, builder_status=BUILDER_STATUS_CREATED)
    except (json.JSONDecodeError, Exception):
        pass

    lines = [
        line.lstrip("0123456789.-) ").strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    lines = [l for l in lines if l]
    if lines:
        steps = [BuilderStep(step=i, action=l) for i, l in enumerate(lines[:9], start=1)]
        return BuilderOutput(builder_output=steps, builder_status=BUILDER_STATUS_CREATED)

    raise ValueError(f"builder LLM 응답 파싱 실패: {content[:200]!r}")


def _run_llm_builder(inp: BuilderInput) -> BuilderOutput:
    url = get_base_url() + CHAT_PATH
    payload = {
        "model": get_builder_model(),
        "messages": [
            {"role": "system", "content": BUILDER_SYSTEM_PROMPT},
            {"role": "user",   "content": build_user_prompt(inp.raw_input, inp.task_type, inp.plan)},
        ],
        "verbosity": get_builder_verbosity(),
    }
    headers = {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type":  "application/json",
    }
    response = httpx.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _parse_llm_output(content)


def run_builder(raw_input: str, task_type: str, plan: list[dict]) -> tuple[BuilderOutput, str | None]:
    """반환: (BuilderOutput, model_id | None)"""
    inp = _prepare_input(raw_input, task_type, plan)
    if not is_llm_ready():
        return _run_fake_builder(inp), None
    return _run_llm_builder(inp), get_builder_model()
