"""Task Slice Queue — slice 순서 관리 + 진행 상태 추적."""
from __future__ import annotations

from src.planning.backward_planner import SlicePlan, TaskSlice


def get_current_slice(plan: SlicePlan, index: int = 0) -> TaskSlice | None:
    """현재 실행할 slice 반환. 범위 초과 시 None."""
    if index < 0 or index >= len(plan.slices):
        return None
    return plan.slices[index]


def advance_slice(plan: SlicePlan, index: int) -> tuple[SlicePlan, int]:
    """현재 slice를 done으로 표시하고 다음 index 반환."""
    if 0 <= index < len(plan.slices):
        plan.slices[index].status = "done"
    return plan, index + 1


def mark_slice_failed(plan: SlicePlan, index: int) -> SlicePlan:
    """현재 slice를 failed로 표시."""
    if 0 <= index < len(plan.slices):
        plan.slices[index].status = "failed"
    return plan


def has_remaining_slices(plan: SlicePlan, index: int) -> bool:
    """남은 slice가 있는지 확인."""
    return index < len(plan.slices)


def reset_slice_for_retry(plan: SlicePlan, index: int) -> SlicePlan:
    """실패한 slice를 pending으로 리셋 (재시도)."""
    if 0 <= index < len(plan.slices):
        plan.slices[index].status = "pending"
    return plan
