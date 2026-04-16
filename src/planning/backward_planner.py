"""Backward Action Planner — deliverable spec에서 역산하여 task slice 생성."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskSlice:
    """단일 실행 단위."""
    slice_id:    int
    description: str
    target_files: list[str] = field(default_factory=list)
    depends_on:  list[int] = field(default_factory=list)
    status:      str = "pending"  # pending | in_progress | done | failed

    def to_dict(self) -> dict:
        return {
            "slice_id": self.slice_id,
            "description": self.description,
            "target_files": self.target_files,
            "depends_on": self.depends_on,
            "status": self.status,
        }


@dataclass
class SlicePlan:
    """전체 slice 계획."""
    slices: list[TaskSlice] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"slices": [s.to_dict() for s in self.slices]}


def build_slice_plan(deliverable_spec: dict, plan_steps: list[dict] | None = None) -> SlicePlan:
    """
    deliverable_spec + planner 결과를 기반으로 task slice 목록 생성.
    v1 baseline: plan_steps를 1:1로 slice에 매핑.
    TODO: LLM으로 역산 분해
    """
    steps = plan_steps or []
    if not steps:
        # plan이 없으면 단일 slice
        return SlicePlan(slices=[
            TaskSlice(
                slice_id=1,
                description=deliverable_spec.get("goal", "단일 작업"),
                target_files=deliverable_spec.get("target_files", []),
            )
        ])

    slices = []
    for i, step in enumerate(steps, start=1):
        desc = step.get("description", "") if isinstance(step, dict) else str(step)
        slices.append(TaskSlice(
            slice_id=i,
            description=desc,
            depends_on=[i - 1] if i > 1 else [],
        ))
    return SlicePlan(slices=slices)
