"""
v4 Orchestrator — Phase 7 래퍼 전용.

v3 전체 파이프라인(run_orchestration 등)은 Phase 0.5~7로 대체됨.
이 파일은 Phase 7 내부에서 호출되는 4개 함수만 유지.

  create_packet_if_approved  — 승인 후 패킷 생성
  save_execution_result_step — 실행 결과 저장
  run_verification           — 결과 검증
  finalize_run_step          — 최종 요약

이 함수들은 src.phases.phase_7_app_dev.handle_* 래퍼를 통해 호출됨.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from src.store.artifact_store import (
    load_artifact, update_artifact,
    update_execution_result, update_final_summary,
)
from src.packet.packet_builder import build_execution_packet, write_packet_file
from src.verification.result_verifier import verify_execution_result
from src.verification.spec_alignment import check_spec_alignment


# ---------------------------------------------------------------------------
# 패킷 생성 (승인 후)
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
# 실행 결과 저장
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
# 검증
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

    v_result = verify_execution_result(exec_result)
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
# 최종 요약
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
