"""
v1 Orchestrator — artifact_store 기반 전체 흐름 관리.

LangGraph invoke → artifact 저장 → 승인/패킷/실행결과/검증/finalize는
CLI 또는 외부에서 단계별 호출.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.graph_flow import build_graph
from src.utils.id_generator import generate_run_id, generate_thread_id
from src.store.artifact_store import (
    save_artifact, load_artifact, update_artifact,
    update_execution_result, update_final_summary,
)
from src.packet.packet_builder import build_execution_packet, write_packet_file
from src.verification.result_verifier import verify_execution_result
from src.verification.spec_alignment import check_spec_alignment


# ---------------------------------------------------------------------------
# 1. 메인 오케스트레이션 (classify ~ approval_prepare)
# ---------------------------------------------------------------------------

def run_orchestration(
    raw_input: str,
    db_path: str,
    doc_only: bool = False,
) -> Dict[str, Any]:
    """
    LangGraph 그래프를 실행하고 결과를 artifact_store에 저장.
    반환: 저장된 artifact dict
    """
    raw_input = raw_input.strip()
    if not raw_input:
        raise ValueError("raw_input must not be empty")

    run_id = generate_run_id()
    thread_id = generate_thread_id()

    app = build_graph()
    graph_result = app.invoke({
        "raw_input": raw_input,
        "doc_only_mode": doc_only,
    })

    # artifact 구성
    artifact: Dict[str, Any] = {
        "run_id":              run_id,
        "thread_id":           thread_id,
        "raw_input":           raw_input,
        "task_type":           graph_result.get("task_type"),

        "research_bundle":     graph_result.get("research_bundle"),
        "initial_document":    graph_result.get("initial_document"),
        "cross_audit_result":  graph_result.get("cross_audit_result"),
        "canonical_doc":       graph_result.get("canonical_doc"),
        "canonical_frozen":    graph_result.get("canonical_frozen"),
        "deliverable_spec":    graph_result.get("deliverable_spec"),

        "slice_plan":          graph_result.get("slice_plan"),
        "current_slice_index": graph_result.get("current_slice_index"),

        "plan":                graph_result.get("plan"),
        "plan_status":         graph_result.get("plan_status"),
        "selected_models":     graph_result.get("selected_models"),
        "builder_output":      graph_result.get("builder_output"),
        "builder_status":      graph_result.get("builder_status"),

        "rule_check_result":   graph_result.get("rule_check_result"),
        "llm_review_result":   graph_result.get("llm_review_result"),
        "reviewer_feedback":   graph_result.get("reviewer_feedback"),

        "approval_required":   graph_result.get("approval_required"),
        "approval_status":     graph_result.get("approval_status"),
        "approval_reason":     graph_result.get("approval_reason"),

        "run_status":          graph_result.get("run_status"),
        "last_node":           graph_result.get("last_node"),
        "error":               graph_result.get("error"),
    }

    save_artifact(db_path, artifact)
    return artifact


# ---------------------------------------------------------------------------
# 2. 패킷 생성 (승인 후)
# ---------------------------------------------------------------------------

def create_packet_if_approved(
    db_path: str,
    base_dir: str,
    run_id: str,
    goal: str,
    approval_status: str,
) -> Dict[str, Any]:
    """승인 상태일 때만 패킷 생성. 비승인 시 차단."""
    if approval_status != "approved":
        return {
            "packet_created": False,
            "packet_path": None,
            "error": "approval_not_granted",
        }

    # artifact에서 deliverable_spec 로드
    artifact = load_artifact(db_path, run_id=run_id)
    spec = artifact.get("deliverable_spec") if artifact else None

    packet = build_execution_packet(
        run_id=run_id,
        goal=goal,
        deliverable_spec=spec,
    )
    packet_path = write_packet_file(base_dir, packet)

    update_artifact(db_path, run_id, {
        "execution_packet": packet.to_dict(),
        "packet_path": packet_path,
        "packet_status": "created",
        "run_status": "packet_ready",
    })

    return {
        "packet_created": True,
        "packet_path": packet_path,
        "error": None,
    }


# ---------------------------------------------------------------------------
# 3. 실행 결과 저장
# ---------------------------------------------------------------------------

def save_execution_result_step(
    db_path: str,
    run_id: str,
    changed_files: list[str],
    test_results: str,
    run_log: str,
) -> None:
    update_execution_result(db_path, run_id, changed_files, test_results, run_log)


# ---------------------------------------------------------------------------
# 4. 검증 (result_verify + spec_alignment)
# ---------------------------------------------------------------------------

def run_verification(
    db_path: str,
    run_id: str,
) -> Dict[str, Any]:
    """실행 결과 검증 + spec alignment 확인."""
    artifact = load_artifact(db_path, run_id=run_id)
    if not artifact:
        return {"error": "artifact not found"}

    exec_result = artifact.get("execution_result")

    # 1. result verification
    v_result = verify_execution_result(exec_result)

    # 2. spec alignment
    a_result = check_spec_alignment(
        execution_result=exec_result or {},
        deliverable_spec=artifact.get("deliverable_spec"),
        canonical_doc=artifact.get("canonical_doc"),
    )

    update_artifact(db_path, run_id, {
        "result_verification": v_result.to_dict(),
        "spec_alignment": a_result.to_dict(),
        "run_status": "verified" if (v_result.passed and a_result.aligned) else "verification_failed",
    })

    return {
        "result_verification": v_result.to_dict(),
        "spec_alignment": a_result.to_dict(),
        "all_passed": v_result.passed and a_result.aligned,
    }


# ---------------------------------------------------------------------------
# 5. 최종 요약
# ---------------------------------------------------------------------------

def finalize_run_step(
    db_path: str,
    run_id: str,
    goal: str,
    approval_status: str,
    changed_files: list[str],
    test_results: str,
    run_log: str,
) -> str:
    from src.finalize.finalize_service import finalize_run
    return finalize_run(
        db_path=db_path,
        run_id=run_id,
        goal=goal,
        approval_status=approval_status,
        changed_files=changed_files,
        test_results=test_results,
        run_log=run_log,
    )


# ---------------------------------------------------------------------------
# 6. Resume from doc_frozen
# ---------------------------------------------------------------------------

def resume_from_doc(db_path: str, run_id: str) -> Dict[str, Any]:
    """
    doc_frozen 상태에서 실행 계획으로 재개.
    deliverable_spec → backward_plan → planner → builder → review → approval
    """
    from src.graph_flow import build_resume_from_doc_graph

    artifact = load_artifact(db_path, run_id=run_id)
    if not artifact:
        raise ValueError(f"artifact not found: {run_id}")
    if artifact.get("run_status") != "doc_frozen":
        raise ValueError(f"run_status must be 'doc_frozen', got '{artifact.get('run_status')}'")

    # 기존 artifact에서 필요한 상태를 그래프 입력으로
    state = {
        "raw_input":        artifact.get("raw_input", ""),
        "task_type":        artifact.get("task_type", ""),
        "canonical_doc":    artifact.get("canonical_doc"),
        "canonical_frozen": artifact.get("canonical_frozen"),
        "research_bundle":  artifact.get("research_bundle"),
    }

    app = build_resume_from_doc_graph()
    graph_result = app.invoke(state)

    # artifact 업데이트
    updates = {
        "deliverable_spec":    graph_result.get("deliverable_spec"),
        "slice_plan":          graph_result.get("slice_plan"),
        "current_slice_index": graph_result.get("current_slice_index"),
        "plan":                graph_result.get("plan"),
        "plan_status":         graph_result.get("plan_status"),
        "selected_models":     graph_result.get("selected_models"),
        "builder_output":      graph_result.get("builder_output"),
        "builder_status":      graph_result.get("builder_status"),
        "rule_check_result":   graph_result.get("rule_check_result"),
        "llm_review_result":   graph_result.get("llm_review_result"),
        "reviewer_feedback":   graph_result.get("reviewer_feedback"),
        "approval_required":   graph_result.get("approval_required"),
        "approval_status":     graph_result.get("approval_status"),
        "approval_reason":     graph_result.get("approval_reason"),
        "run_status":          graph_result.get("run_status"),
        "last_node":           graph_result.get("last_node"),
    }
    update_artifact(db_path, run_id, updates)

    # 새 artifact 로드해서 반환
    return load_artifact(db_path, run_id=run_id)


# ---------------------------------------------------------------------------
# 7. Slice 반복 실행 (more slices → slice_queue 복귀)
# ---------------------------------------------------------------------------

def run_next_slice(db_path: str, run_id: str) -> Dict[str, Any]:
    """
    다음 slice에 대해 planner → builder → review → approval 실행.
    남은 slice가 없으면 에러.
    """
    from src.graph_flow import build_slice_iteration_graph
    from src.planning.slice_queue import get_current_slice, has_remaining_slices

    artifact = load_artifact(db_path, run_id=run_id)
    if not artifact:
        raise ValueError(f"artifact not found: {run_id}")

    slice_plan_dict = artifact.get("slice_plan", {})
    slices = slice_plan_dict.get("slices", [])
    current_idx = artifact.get("current_slice_index", 0)

    if current_idx >= len(slices):
        return {"error": "no_remaining_slices", "run_id": run_id}

    current_slice = slices[current_idx]

    state = {
        "raw_input":        current_slice.get("description", artifact.get("raw_input", "")),
        "task_type":        artifact.get("task_type", ""),
        "deliverable_spec": artifact.get("deliverable_spec"),
        "canonical_doc":    artifact.get("canonical_doc"),
    }

    app = build_slice_iteration_graph()
    graph_result = app.invoke(state)

    updates = {
        "plan":                graph_result.get("plan"),
        "plan_status":         graph_result.get("plan_status"),
        "selected_models":     graph_result.get("selected_models"),
        "builder_output":      graph_result.get("builder_output"),
        "builder_status":      graph_result.get("builder_status"),
        "rule_check_result":   graph_result.get("rule_check_result"),
        "llm_review_result":   graph_result.get("llm_review_result"),
        "reviewer_feedback":   graph_result.get("reviewer_feedback"),
        "approval_required":   graph_result.get("approval_required"),
        "approval_status":     graph_result.get("approval_status"),
        "approval_reason":     graph_result.get("approval_reason"),
        "run_status":          graph_result.get("run_status"),
        "last_node":           graph_result.get("last_node"),
        "current_slice_index": current_idx,  # 아직 advance 안 함
    }
    update_artifact(db_path, run_id, updates)
    return load_artifact(db_path, run_id=run_id)


# ---------------------------------------------------------------------------
# 8. 실패 복구 진입점
# ---------------------------------------------------------------------------

def retry_current_slice(db_path: str, run_id: str) -> Dict[str, Any]:
    """
    slice_issue 복구 — 현재 slice를 advance 없이 재실행.
    run_status를 'waiting_approval'로 리셋한 뒤 run_next_slice() 위임.
    """
    artifact = load_artifact(db_path, run_id=run_id)
    if not artifact:
        raise ValueError(f"artifact not found: {run_id}")

    # 재실행 전 상태 초기화 (이전 실패 결과 제거)
    update_artifact(db_path, run_id, {
        "execution_result": None,
        "result_verification": None,
        "spec_alignment": None,
        "run_status": "waiting_retry_slice",
    })
    return run_next_slice(db_path, run_id)


def reaudit_doc(
    db_path: str,
    run_id: str,
    patched_target_files: Optional[list] = None,
) -> Dict[str, Any]:
    """
    doc_issue 복구 — deliverable_spec.target_files를 교정한 뒤
    unfreeze → cross_audit → re-freeze → deliverable_spec 재생성.

    patched_target_files: None이면 기존 changed_files로 자동 채움.
    반환: 업데이트된 artifact dict
    """
    from src.document.canonical_freeze import unfreeze_for_reaudit, CanonicalDoc, freeze_document
    from src.document.cross_audit import run_cross_audit
    from src.document.deliverable_spec import build_deliverable_spec

    artifact = load_artifact(db_path, run_id=run_id)
    if not artifact:
        raise ValueError(f"artifact not found: {run_id}")

    # 1. target_files 결정
    if patched_target_files is None:
        exec_result = artifact.get("execution_result") or {}
        patched_target_files = exec_result.get("changed_files", [])

    if not patched_target_files:
        raise ValueError("patched_target_files가 비어있음 — 범위를 명시하세요")

    # 2. canonical_doc unfreeze
    canonical_raw = artifact.get("canonical_doc") or {}
    canonical = CanonicalDoc(
        document=canonical_raw.get("document", canonical_raw),
        frozen=canonical_raw.get("frozen", False),
        frozen_at=canonical_raw.get("frozen_at", ""),
        version=canonical_raw.get("version", 1),
    )
    unfrozen = unfreeze_for_reaudit(canonical)

    # 3. cross_audit 재실행
    audit_result = run_cross_audit(unfrozen.document)

    # 4. re-freeze — unfreeze_for_reaudit이 올린 version 인계 (freeze_document는 항상 v1으로 초기화하므로 직접 구성)
    from datetime import datetime, timezone
    refrozen = CanonicalDoc(
        document=unfrozen.document,
        frozen=audit_result.passed,
        frozen_at=datetime.now(timezone.utc).isoformat() if audit_result.passed else "",
        version=unfrozen.version,
    )

    # 5. deliverable_spec target_files 교정
    existing_spec = artifact.get("deliverable_spec") or {}
    patched_spec = {
        **existing_spec,
        "target_files": patched_target_files,
    }

    update_artifact(db_path, run_id, {
        "canonical_doc":      refrozen.to_dict(),
        "canonical_frozen":   refrozen.frozen,
        "cross_audit_result": audit_result.to_dict(),
        "deliverable_spec":   patched_spec,
        "result_verification": None,
        "spec_alignment":     None,
        "execution_result":   None,
        "run_status":         "doc_reaudited",
    })
    return load_artifact(db_path, run_id=run_id)


def advance_current_slice(db_path: str, run_id: str) -> Dict[str, Any]:
    """현재 slice를 done으로 표시하고 다음 인덱스로 전진."""
    artifact = load_artifact(db_path, run_id=run_id)
    if not artifact:
        raise ValueError(f"artifact not found: {run_id}")

    slice_plan_dict = artifact.get("slice_plan", {})
    slices = slice_plan_dict.get("slices", [])
    current_idx = artifact.get("current_slice_index", 0)

    if 0 <= current_idx < len(slices):
        slices[current_idx]["status"] = "done"

    new_idx = current_idx + 1
    has_more = new_idx < len(slices)

    update_artifact(db_path, run_id, {
        "slice_plan": {"slices": slices},
        "current_slice_index": new_idx,
        "run_status": "waiting_next_slice" if has_more else "all_slices_done",
    })
    return {
        "current_slice_index": new_idx,
        "has_remaining": has_more,
    }
