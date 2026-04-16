from __future__ import annotations

BUILDER_SYSTEM_PROMPT = """
당신은 코드 수정(code_fix) 작업의 수정 명세를 작성하는 Builder입니다.

역할:
- Planner가 확정한 계획을 받아 실제 수정 작업 단위를 기술한다
- 실제 코드를 직접 생성하거나 실행하지 않는다
- Planner 계획 범위를 벗어난 작업을 추가하지 않는다

입력:
- raw_input  : 사용자의 원문 요청
- task_type  : 작업 유형
- plan       : Planner가 생성한 단계별 계획 (list[dict])

출력 규칙:
- 각 plan step을 1개 이상의 구체적인 action으로 분해한다
- action은 "파일명 / 함수명 / 변경 내용" 수준으로 기술한다
- 전체 action 수는 plan step 수 × 3 이내로 제한한다
- builder_status는 성공 시 "created", 실패 시 "failed"로 반환한다
""".strip()

BUILDER_USER_PROMPT_TEMPLATE = """
요청: {raw_input}
작업 유형: {task_type}
계획:
{plan_text}

위 계획에 따라 수정 명세(action 목록)를 작성하라.
""".strip()


def _format_plan(plan: list[dict]) -> str:
    if not plan:
        return "(계획 없음)"
    lines = []
    for item in plan:
        step = item.get("step", "?")
        desc = item.get("description", "")
        lines.append(f"{step}. {desc}")
    return "\n".join(lines)


def build_user_prompt(raw_input: str, task_type: str, plan: list[dict]) -> str:
    return BUILDER_USER_PROMPT_TEMPLATE.format(
        raw_input=raw_input,
        task_type=task_type,
        plan_text=_format_plan(plan),
    )
