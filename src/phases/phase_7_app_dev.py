"""
Phase 7 · 앱개발 실행 (Day 121, Step 10)

역할: Phase 6 BridgeDecision의 deliverable_spec을 받아 앱개발 파이프라인 실행.
  진입: deliverable_spec + raw_input
  수행: planner → builder → review → approval_prepare (LangGraph 서브그래프)
  이후: 승인/패킷/실행결과/검증/finalize는 기존 v3 orchestrator 재사용

설계 원칙 (Step 10 결정사항):
  1. classifier / research / document 단계 건너뛰기 — Phase 0.5~4가 대체
  2. planner 이후 기존 v3 로직 100% 재사용
  3. graph_flow.build_phase_7_graph()를 서브그래프로 사용
  4. 공개 API 5개: run_phase_7_from_spec + handle_* 4개

호출 경로:
  CLI/Web → Phase 6 decide_track("app_dev") → BridgeDecision
         → run_phase_7_from_spec(spec, raw_input)
         → (승인) → handle_approval → handle_packet
         → Cursor 실행 → handle_execution_result
         → handle_verification → handle_finalize

환경변수 변경 없음 (기존 planner/builder/reviewer 환경변수 재사용).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.store.artifact_store import save_artifact, utc_now_iso
from src.utils.id_generator import generate_run_id, generate_thread_id


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

STATUS_OK = "ok"
STATUS_FAILED = "failed"


@dataclass
class Phase7Result:
    """Phase 7 진입 결과 (planner~approval_prepare 완료 후)."""
    status: str = STATUS_OK
    run_id: str = ""
    thread_id: str = ""

    plan: Optional[List[Dict[str, Any]]] = None
    builder_output: Optional[List[Dict[str, Any]]] = None
    reviewer_feedback: Optional[List[str]] = None

    approval_required: bool = False
    approval_status: str = ""
    approval_reason: str = ""

    run_status: str = ""
    last_node: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "plan": self.plan,
            "builder_output": self.builder_output,
            "reviewer_feedback": self.reviewer_feedback,
            "approval_required": self.approval_required,
            "approval_status": self.approval_status,
            "approval_reason": self.approval_reason,
            "run_status": self.run_status,
            "last_node": self.last_node,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# 1. 공개 API — run_phase_7_from_spec
# ---------------------------------------------------------------------------

def run_phase_7_from_spec(
    deliverable_spec: Dict[str, Any],
    raw_input: str,
    db_path: str,
    project_id: Optional[str] = None,
    task_type: str = "feature",
) -> Phase7Result:
    """
    Phase 6이 만든 spec을 받아 Phase 7 진입.
    planner → builder → review_gate → approval_prepare 까지 실행.

    Args:
      deliverable_spec: Phase 6 BridgeDecision.deliverable_spec
      raw_input: 원본 사용자 요청
      db_path: 아티팩트 저장 경로
      project_id: 프로젝트 ID (v4 프로젝트 단위 관리용, 선택)
      task_type: 기본 "feature", 필요시 "code_fix" 등

    Returns:
      Phase7Result (예외 전파 없음)

    실패 정책:
      - spec 유효성 실패 → Phase7Result(status=failed, error=...)
      - 그래프 실행 실패 → Phase7Result(status=failed, error=...)
    """
    # 1. 입력 검증
    if not isinstance(deliverable_spec, dict):
        return Phase7Result(status=STATUS_FAILED, error="deliverable_spec이 dict가 아님")

    if not deliverable_spec.get("description", "").strip():
        return Phase7Result(
            status=STATUS_FAILED,
            error="deliverable_spec.description이 비어있음",
        )

    if not isinstance(raw_input, str) or not raw_input.strip():
        return Phase7Result(status=STATUS_FAILED, error="raw_input이 비어있음")

    # 2. 식별자 생성
    run_id = generate_run_id()
    thread_id = generate_thread_id()

    # 3. 그래프 실행
    try:
        from src.graph_flow import build_phase_7_graph
    except ImportError as exc:
        return Phase7Result(
            status=STATUS_FAILED,
            run_id=run_id,
            error=f"graph_flow.build_phase_7_graph 없음: {exc}",
        )

    try:
        app = build_phase_7_graph()
        graph_result = app.invoke({
            "raw_input": raw_input.strip(),
            "task_type": task_type,
            "deliverable_spec": deliverable_spec,
        })
    except Exception as exc:
        return Phase7Result(
            status=STATUS_FAILED,
            run_id=run_id,
            thread_id=thread_id,
            error=f"그래프 실행 실패: {type(exc).__name__}: {str(exc)[:200]}",
        )

    # 4. artifact 저장 (v3 스키마 + v4 project_id)
    artifact: Dict[str, Any] = {
        "run_id":              run_id,
        "thread_id":           thread_id,
        "raw_input":           raw_input.strip(),
        "task_type":           task_type,
        "project_id":          project_id,
        "phase":               "phase_7",

        "deliverable_spec":    deliverable_spec,

        "plan":                graph_result.get("plan"),
        "plan_status":         graph_result.get("plan_status"),
        "selected_models":     graph_result.get("selected_models"),
        "builder_output":      graph_result.get("builder_output"),
        "builder_status":      graph_result.get("builder_status"),

        "rule_check_result":   graph_result.get("rule_check_result"),
        "llm_review_result":   graph_result.get("llm_review_result"),
        "reviewer_feedback":   graph_result.get("reviewer_feedback"),

        "approval_required":   graph_result.get("approval_required", False),
        "approval_status":     graph_result.get("approval_status", ""),
        "approval_reason":     graph_result.get("approval_reason", ""),

        "run_status":          graph_result.get("run_status", "waiting_approval"),
        "last_node":           graph_result.get("last_node", ""),
        "error":               graph_result.get("error"),
    }

    try:
        save_artifact(db_path, artifact)
    except Exception as exc:
        return Phase7Result(
            status=STATUS_FAILED,
            run_id=run_id,
            thread_id=thread_id,
            error=f"artifact 저장 실패: {type(exc).__name__}: {str(exc)[:200]}",
        )

    # 5. 성공 반환
    return Phase7Result(
        status=STATUS_OK,
        run_id=run_id,
        thread_id=thread_id,
        plan=graph_result.get("plan"),
        builder_output=graph_result.get("builder_output"),
        reviewer_feedback=graph_result.get("reviewer_feedback"),
        approval_required=graph_result.get("approval_required", False),
        approval_status=graph_result.get("approval_status", ""),
        approval_reason=graph_result.get("approval_reason", ""),
        run_status=graph_result.get("run_status", "waiting_approval"),
        last_node=graph_result.get("last_node", ""),
        error=graph_result.get("error"),
    )


# ---------------------------------------------------------------------------
# 2. 공개 API — handle_approval
# ---------------------------------------------------------------------------

def handle_approval(
    db_path: str,
    run_id: str,
    decision: str,
) -> Dict[str, Any]:
    """
    사용자 승인 결정 적용 (기존 v3 apply_user_approval 래퍼).

    Args:
      db_path
      run_id: Phase 7 생성 시 반환된 run_id
      decision: "approve" | "reject"

    Returns:
      {"ok": bool, "approval_status": str, "error": Optional[str]}
    """
    decision = (decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        return {
            "ok": False,
            "approval_status": "",
            "error": f"decision은 'approve' 또는 'reject'여야 함. 받은 값: {decision!r}",
        }

    try:
        from src.approval.approval_service import apply_user_approval
        apply_user_approval(db_path, run_id, decision)
        return {
            "ok": True,
            "approval_status": decision,  # "approve" / "reject"
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "approval_status": "",
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


# ---------------------------------------------------------------------------
# 3. 공개 API — handle_packet
# ---------------------------------------------------------------------------

def handle_packet(
    db_path: str,
    run_id: str,
    base_dir: str = ".",
) -> Dict[str, Any]:
    """
    승인된 run에 대해 Cursor 실행 패킷 생성 (기존 orchestrator.create_packet_if_approved 래퍼).

    Returns:
      {
        "packet_created": bool,
        "packet_path": Optional[str],
        "error": Optional[str],
      }
    """
    try:
        from src.orchestrator import create_packet_if_approved
        from src.store.artifact_store import load_artifact

        artifact = load_artifact(db_path, run_id=run_id)
        if not artifact:
            return {
                "packet_created": False,
                "packet_path": None,
                "error": f"run_id를 찾을 수 없음: {run_id}",
            }

        result = create_packet_if_approved(
            db_path=db_path,
            base_dir=base_dir,
            run_id=run_id,
            goal=artifact.get("raw_input", ""),
            approval_status=artifact.get("approval_status", ""),
        )
        return result
    except Exception as exc:
        return {
            "packet_created": False,
            "packet_path": None,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


# ---------------------------------------------------------------------------
# 4. 공개 API — handle_execution_result
# ---------------------------------------------------------------------------

def handle_execution_result(
    db_path: str,
    run_id: str,
    changed_files: List[str],
    test_results: str,
    run_log: str,
) -> Dict[str, Any]:
    """
    Cursor 실행 결과 저장 (기존 save_execution_result_step 래퍼).
    """
    try:
        from src.orchestrator import save_execution_result_step
        save_execution_result_step(
            db_path=db_path,
            run_id=run_id,
            changed_files=changed_files or [],
            test_results=test_results or "",
            run_log=run_log or "",
        )
        return {"ok": True, "error": None}
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


# ---------------------------------------------------------------------------
# 5. 공개 API — handle_verification
# ---------------------------------------------------------------------------

def handle_verification(db_path: str, run_id: str) -> Dict[str, Any]:
    """
    실행 결과 검증 (기존 run_verification 래퍼).

    Returns:
      {
        "ok": bool,
        "result_verification": dict,
        "spec_alignment": dict,
        "all_passed": bool,
        "error": Optional[str],
      }
    """
    try:
        from src.orchestrator import run_verification
        result = run_verification(db_path, run_id)
        return {
            "ok": True,
            "result_verification": result.get("result_verification", {}),
            "spec_alignment": result.get("spec_alignment", {}),
            "all_passed": result.get("all_passed", False),
            "error": result.get("error"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "result_verification": {},
            "spec_alignment": {},
            "all_passed": False,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


# ---------------------------------------------------------------------------
# 6. 공개 API — handle_finalize
# ---------------------------------------------------------------------------

def handle_finalize(db_path: str, run_id: str) -> Dict[str, Any]:
    """
    최종 요약 생성 + 완료 처리 (기존 finalize_run_step 래퍼).

    Returns:
      {"ok": bool, "summary": str, "error": Optional[str]}
    """
    try:
        from src.orchestrator import finalize_run_step
        from src.store.artifact_store import load_artifact

        artifact = load_artifact(db_path, run_id=run_id)
        if not artifact:
            return {
                "ok": False,
                "summary": "",
                "error": f"run_id를 찾을 수 없음: {run_id}",
            }

        exec_result = artifact.get("execution_result") or {}
        summary = finalize_run_step(
            db_path=db_path,
            run_id=run_id,
            goal=artifact.get("raw_input", ""),
            approval_status=artifact.get("approval_status", ""),
            changed_files=exec_result.get("changed_files", []),
            test_results=exec_result.get("test_results", ""),
            run_log=exec_result.get("run_log", ""),
        )
        return {"ok": True, "summary": summary, "error": None}
    except Exception as exc:
        return {
            "ok": False,
            "summary": "",
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }
