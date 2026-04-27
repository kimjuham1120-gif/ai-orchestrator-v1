"""
src/web/handlers.py — v4 웹 UI용 Phase 호출 핸들러 (Day 122~)

역할: FastAPI 라우터와 Phase 모듈 사이의 얇은 어댑터.
  - 각 Phase의 공개 API를 호출
  - 결과를 UI 친화적 dict로 변환
  - DB 저장/조회 관리 (project + artifacts)

설계 원칙:
  - 비즈니스 로직은 Phase 모듈에 있음. 여기서는 호출만.
  - 모든 함수는 dict 반환 (템플릿에서 바로 사용 가능)
  - 예외는 {"ok": False, "error": ...}로 변환 (UI 레이어 보호)
"""
from __future__ import annotations

from typing import Any, Dict

from src.store.artifact_store import (
    load_project, save_project, update_project_phase,
    list_project_runs, update_artifact, save_artifact,
    utc_now_iso,
)
from src.utils.id_generator import generate_run_id, generate_thread_id
from src.utils.llm_utils import set_llm_context, clear_llm_context


# ---------------------------------------------------------------------------
# 프로젝트 ID 생성
# ---------------------------------------------------------------------------

def _new_project_id() -> str:
    """프로젝트 ID 생성 — run_id와 구분하기 위해 proj- 접두어."""
    import uuid
    return f"proj-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Phase 0.5 · 처리 가능성 게이트
# ---------------------------------------------------------------------------

def handle_phase_0_5(
    raw_input: str,
    db_path: str,
    template_text: str = "",
    project_type: str = "doc_generation",
    referenced_context: dict = None,
) -> Dict[str, Any]:
    """
    새 프로젝트 생성 + Phase 0.5 실행.

    Args:
      raw_input: 사용자 요청
      db_path: DB 경로
      template_text: 양식 파일 텍스트 (선택, 문서 생성 모드에서 Phase 3가 사용)
      project_type: "doc_generation" | "app_dev"
      referenced_context: 앱개발 모드에서 업로드된 기획문서 묶음 (선택)

    Returns:
      {
        "ok": bool,
        "project_id": str,
        "verdict": str,
        "reason": str,
        "suggested_clarification": Optional[str],
        "error": Optional[str],
      }
    """
    try:
        from src.phases.phase_0_5_gate import check_feasibility
    except ImportError as exc:
        return {"ok": False, "error": f"Phase 0.5 모듈 없음: {exc}"}

    text = (raw_input or "").strip()
    if not text:
        return {"ok": False, "error": "요청이 비어있습니다"}

    # 로깅을 위해 ID들을 LLM 호출 전에 생성
    project_id = _new_project_id()
    run_id = generate_run_id()
    set_llm_context(
        db_path=db_path,
        project_id=project_id,
        run_id=run_id,
        phase="phase_0_5",
    )

    # Phase 0.5 실행 (내부 call_llm이 자동으로 llm_calls에 기록됨)
    try:
        result = check_feasibility(text)
    except Exception as exc:
        clear_llm_context()
        return {"ok": False, "error": f"Phase 0.5 실행 실패: {exc}"}

    # 프로젝트 생성
    now = utc_now_iso()

    try:
        save_project(db_path, {
            "project_id": project_id,
            "title": text[:80],
            "raw_input": text,
            "created_at": now,
            "updated_at": now,
            "current_phase": "phase_0_5",
            "status": "in_progress" if result.verdict == "possible" else "blocked",
            "project_type": project_type,
        })
    except Exception as exc:
        clear_llm_context()
        return {"ok": False, "error": f"프로젝트 저장 실패: {exc}"}

    # artifact 저장 (Phase 0.5 결과)
    try:
        save_artifact(db_path, {
            "run_id": run_id,
            "thread_id": generate_thread_id(),
            "project_id": project_id,
            "phase": "phase_0_5",
            "raw_input": text,
            "feasibility_result": result.to_dict(),
            "template_text": template_text or None,            # 문서 모드용 양식
            "project_type": project_type,                       # Step 15
            "referenced_context": referenced_context,           # Step 15: 앱개발 모드 기획문서
            "todo_status": "pending" if project_type == "app_dev" else None,
            "run_status": "phase_0_5_done",
        })
    except Exception:
        # artifact 저장 실패해도 프로젝트는 생성됨 — 경고만
        pass

    clear_llm_context()

    return {
        "ok": True,
        "project_id": project_id,
        "verdict": result.verdict,
        "reason": result.reason,
        "suggested_clarification": result.suggested_clarification,
        "decided_by": result.decided_by,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Phase 1 · 서브주제 분해
# ---------------------------------------------------------------------------

def handle_phase_1(project_id: str, db_path: str) -> Dict[str, Any]:
    """Phase 1 실행 — 프로젝트의 raw_input으로 서브주제 분해."""
    try:
        from src.phases.phase_1_decompose import decompose_request
    except ImportError as exc:
        return {"ok": False, "error": f"Phase 1 모듈 없음: {exc}"}

    project = load_project(db_path, project_id)
    if not project:
        return {"ok": False, "error": f"프로젝트 없음: {project_id}"}

    # 기존 run_id 가져오기 (Phase 0.5에서 생성됨)
    runs = list_project_runs(db_path, project_id)
    run_id = runs[0]["run_id"] if runs else None

    set_llm_context(
        db_path=db_path,
        project_id=project_id,
        run_id=run_id,
        phase="phase_1",
    )

    try:
        result = decompose_request(project["raw_input"])
    except Exception as exc:
        clear_llm_context()
        return {"ok": False, "error": f"Phase 1 실행 실패: {exc}"}

    # artifact 업데이트 (같은 project_id의 Phase 0.5 artifact 찾아 업데이트)
    if runs:
        update_artifact(db_path, run_id, {
            "phase": "phase_1",
            "subtopics": result.subtopics,
            "run_status": "phase_1_done",
        })

    update_project_phase(db_path, project_id, "phase_1")
    clear_llm_context()

    return {
        "ok": True,
        "project_id": project_id,
        "subtopics": result.subtopics,
        "decided_by": result.decided_by,
        "warning": result.error,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Phase 2 · 병렬 리서치
# ---------------------------------------------------------------------------

def handle_phase_2(project_id: str, db_path: str, mode: str = "web_search") -> Dict[str, Any]:
    """
    Phase 2 실행 — 동기 + 타임아웃 방식 (MVP).

    Args:
        mode: "web_search" (기본, 빠름/저렴) 또는 "deep_research" (느림/품질↑)
    """
    try:
        from src.research_v2.phase2_bridge import (
            run_phase_2_research as run_parallel_research, AllSubtopicsFailedError,
        )
    except ImportError as exc:
        return {"ok": False, "error": f"Phase 2 모듈 없음: {exc}"}

    runs = list_project_runs(db_path, project_id)
    if not runs:
        return {"ok": False, "error": f"프로젝트 없음: {project_id}"}

    subtopics = runs[0].get("subtopics") or []
    if not subtopics:
        return {"ok": False, "error": "서브주제 없음 — Phase 1 먼저 실행"}

    set_llm_context(
        db_path=db_path,
        project_id=project_id,
        run_id=runs[0]["run_id"],
        phase="phase_2",
    )

    try:
        result = run_parallel_research(subtopics, mode=mode)
    except AllSubtopicsFailedError as exc:
        update_artifact(db_path, runs[0]["run_id"], {
            "phase": "phase_2",
            "run_status": "phase_2_failed",
        })
        clear_llm_context()
        return {"ok": False, "error": f"모든 리서치 실패: {exc}"}
    except Exception as exc:
        clear_llm_context()
        return {"ok": False, "error": f"Phase 2 실행 실패: {exc}"}

    update_artifact(db_path, runs[0]["run_id"], {
        "phase": "phase_2",
        "parallel_research": result.data,
        "run_status": "phase_2_done",
    })
    update_project_phase(db_path, project_id, "phase_2")
    clear_llm_context()

    return {
        "ok": True,
        "project_id": project_id,
        "total_subtopics": result.total_subtopics,
        "successful_subtopics": result.successful_subtopics,
        "failed_subtopics": result.failed_subtopics,
        "total_adapter_calls": result.total_adapter_calls,
        "successful_adapter_calls": result.successful_adapter_calls,
        "data": result.data,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Phase 3 · 2문서 합성
# ---------------------------------------------------------------------------

def handle_phase_3(project_id: str, db_path: str) -> Dict[str, Any]:
    """Phase 3 실행 — base_info_doc + target_doc 생성."""
    try:
        from src.phases.phase_3_synthesize import synthesize_documents
    except ImportError as exc:
        return {"ok": False, "error": f"Phase 3 모듈 없음: {exc}"}

    runs = list_project_runs(db_path, project_id)
    if not runs:
        return {"ok": False, "error": f"프로젝트 없음: {project_id}"}

    artifact = runs[0]
    project = load_project(db_path, project_id)
    if not project:
        return {"ok": False, "error": "프로젝트 정보 없음"}

    research = artifact.get("parallel_research") or {}
    if not research:
        return {"ok": False, "error": "리서치 결과 없음 — Phase 2 먼저 실행"}

    # 양식 파일 텍스트 (Phase 0.5에서 저장됨, 선택)
    template_text = artifact.get("template_text") or ""

    set_llm_context(
        db_path=db_path,
        project_id=project_id,
        run_id=artifact["run_id"],
        phase="phase_3",
    )

    try:
        result = synthesize_documents(
            project["raw_input"],
            research,
            template_text=template_text,
        )
    except Exception as exc:
        clear_llm_context()
        return {"ok": False, "error": f"Phase 3 실행 실패: {exc}"}

    update_artifact(db_path, artifact["run_id"], {
        "phase": "phase_3",
        "base_info_doc": result.base_info_doc,
        "target_doc": result.target_doc,
        "run_status": "phase_3_done" if result.any_success else "phase_3_failed",
    })
    update_project_phase(db_path, project_id, "phase_3")
    clear_llm_context()

    return {
        "ok": result.any_success,
        "project_id": project_id,
        "base_info_doc": result.base_info_doc,
        "target_doc": result.target_doc,
        "base_info_status": result.base_info_status,
        "target_doc_status": result.target_doc_status,
        "error": result.error if not result.any_success else None,
    }


# ---------------------------------------------------------------------------
# Phase 4 · 3감사관 + 통합
# ---------------------------------------------------------------------------

def handle_phase_4(project_id: str, db_path: str) -> Dict[str, Any]:
    """Phase 4 실행 — 3감사관 + 통합 LLM."""
    try:
        from src.phases.phase_4_audit import run_cross_audit
    except ImportError as exc:
        return {"ok": False, "error": f"Phase 4 모듈 없음: {exc}"}

    runs = list_project_runs(db_path, project_id)
    if not runs:
        return {"ok": False, "error": f"프로젝트 없음: {project_id}"}

    artifact = runs[0]
    project = load_project(db_path, project_id)
    if not project:
        return {"ok": False, "error": "프로젝트 정보 없음"}

    target_doc = artifact.get("target_doc")
    if not target_doc:
        return {"ok": False, "error": "target_doc 없음 — Phase 3 먼저 실행"}

    base_info_doc = artifact.get("base_info_doc")

    set_llm_context(
        db_path=db_path,
        project_id=project_id,
        run_id=artifact["run_id"],
        phase="phase_4",
    )

    try:
        result = run_cross_audit(
            target_doc=target_doc,
            raw_input=project["raw_input"],
            base_info_doc=base_info_doc,
        )
    except Exception as exc:
        clear_llm_context()
        return {"ok": False, "error": f"Phase 4 실행 실패: {exc}"}

    # synthesized_doc이 있으면 target_doc을 업데이트
    updates: Dict[str, Any] = {
        "phase": "phase_4",
        "cross_audit_v4": result.to_dict(),
        "run_status": "phase_4_done" if result.is_success else "phase_4_failed",
    }
    if result.synthesized_doc:
        updates["target_doc"] = result.synthesized_doc  # 고도화본으로 교체

    update_artifact(db_path, artifact["run_id"], updates)
    update_project_phase(db_path, project_id, "phase_4")
    clear_llm_context()

    return {
        "ok": True,  # skipped도 ok (사용자가 OFF 선택 가능)
        "project_id": project_id,
        "enabled": result.enabled,
        "status": result.status,
        "audits": result.audits,
        "synthesized_doc": result.synthesized_doc,
        "successful_auditors": result.successful_auditors,
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# Phase 5 · 사용자 검수 루프
# ---------------------------------------------------------------------------

def handle_phase_5_feedback(
    project_id: str,
    db_path: str,
    user_feedback: str,
) -> Dict[str, Any]:
    """사용자 피드백 적용 — 새 버전 생성 + 이력 추가."""
    try:
        from src.phases.phase_5_feedback import apply_feedback, append_version
    except ImportError as exc:
        return {"ok": False, "error": f"Phase 5 모듈 없음: {exc}"}

    if not user_feedback or not user_feedback.strip():
        return {"ok": False, "error": "피드백이 비어있음"}

    runs = list_project_runs(db_path, project_id)
    if not runs:
        return {"ok": False, "error": f"프로젝트 없음: {project_id}"}

    artifact = runs[0]
    project = load_project(db_path, project_id)
    if not project:
        return {"ok": False, "error": "프로젝트 정보 없음"}

    current_doc = artifact.get("target_doc")
    if not current_doc:
        return {"ok": False, "error": "현재 문서 없음"}

    base_info = artifact.get("base_info_doc")

    set_llm_context(
        db_path=db_path,
        project_id=project_id,
        run_id=artifact["run_id"],
        phase="phase_5",
    )

    try:
        result = apply_feedback(
            current_doc=current_doc,
            user_feedback=user_feedback,
            raw_input=project["raw_input"],
            base_info_doc=base_info,
        )
    except Exception as exc:
        clear_llm_context()
        return {"ok": False, "error": f"Phase 5 실행 실패: {exc}"}

    if not result.is_success:
        clear_llm_context()
        return {"ok": False, "error": result.error or "피드백 적용 실패"}

    # 버전 이력 업데이트
    existing_versions = artifact.get("doc_versions") or []
    new_versions = append_version(
        existing_versions, result.new_doc, feedback_applied=user_feedback.strip(),
    )

    update_artifact(db_path, artifact["run_id"], {
        "phase": "phase_5",
        "target_doc": result.new_doc,
        "doc_versions": new_versions,
        "run_status": "phase_5_active",
    })
    update_project_phase(db_path, project_id, "phase_5")
    clear_llm_context()

    return {
        "ok": True,
        "project_id": project_id,
        "new_doc": result.new_doc,
        "version_count": len(new_versions),
        "error": None,
    }


def handle_phase_5_confirm(project_id: str, db_path: str) -> Dict[str, Any]:
    """사용자가 현재 문서를 최종 확정."""
    try:
        from src.phases.phase_5_feedback import confirm_final
    except ImportError as exc:
        return {"ok": False, "error": f"Phase 5 모듈 없음: {exc}"}

    runs = list_project_runs(db_path, project_id)
    if not runs:
        return {"ok": False, "error": f"프로젝트 없음: {project_id}"}

    current_doc = runs[0].get("target_doc")
    if not current_doc:
        return {"ok": False, "error": "확정할 문서 없음"}

    result = confirm_final(current_doc)
    if not result.confirmed:
        return {"ok": False, "error": result.error}

    update_artifact(db_path, runs[0]["run_id"], {
        "run_status": "phase_5_confirmed",
    })
    update_project_phase(db_path, project_id, "phase_5_confirmed")

    return {
        "ok": True,
        "project_id": project_id,
        "confirmed_at": result.confirmed_at,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Phase 6 · 트랙 전환
# ---------------------------------------------------------------------------

def handle_phase_6(project_id: str, db_path: str, user_decision: str) -> Dict[str, Any]:
    """Phase 6 — 문서 완료 / 앱개발 / 취소 결정."""
    try:
        from src.phases.phase_6_bridge import decide_track
    except ImportError as exc:
        return {"ok": False, "error": f"Phase 6 모듈 없음: {exc}"}

    runs = list_project_runs(db_path, project_id)
    if not runs:
        return {"ok": False, "error": f"프로젝트 없음: {project_id}"}

    artifact = runs[0]
    project = load_project(db_path, project_id)
    if not project:
        return {"ok": False, "error": "프로젝트 정보 없음"}

    target_doc = artifact.get("target_doc")

    decision = decide_track(
        user_decision=user_decision,
        raw_input=project["raw_input"],
        target_doc=target_doc,
    )

    update_artifact(db_path, artifact["run_id"], {
        "phase": "phase_6",
        "bridge_decision": decision.to_dict(),
        "run_status": "phase_6_done" if decision.is_valid else "phase_6_failed",
    })

    # 프로젝트 상태 갱신
    if decision.is_valid:
        if decision.decision == "document_done":
            update_project_phase(db_path, project_id, "phase_6_document_done", status="completed")
        elif decision.decision == "app_dev":
            update_project_phase(db_path, project_id, "phase_6_app_dev")
        elif decision.decision == "cancel":
            update_project_phase(db_path, project_id, "phase_6_cancel", status="cancelled")

    return {
        "ok": decision.is_valid,
        "project_id": project_id,
        "decision": decision.decision,
        "next_phase": decision.next_phase,
        "deliverable_spec": decision.deliverable_spec,
        "reason": decision.reason,
        "error": decision.error,
    }


# ---------------------------------------------------------------------------
# Phase 7 · 앱개발 실행
# ---------------------------------------------------------------------------

def handle_phase_7_start(project_id: str, db_path: str) -> Dict[str, Any]:
    """Phase 6 app_dev 결정 후 Phase 7 진입."""
    try:
        from src.phases.phase_7_app_dev import run_phase_7_from_spec
    except ImportError as exc:
        return {"ok": False, "error": f"Phase 7 모듈 없음: {exc}"}

    runs = list_project_runs(db_path, project_id)
    if not runs:
        return {"ok": False, "error": f"프로젝트 없음: {project_id}"}

    artifact = runs[0]
    project = load_project(db_path, project_id)
    if not project:
        return {"ok": False, "error": "프로젝트 정보 없음"}

    bridge = artifact.get("bridge_decision") or {}
    if bridge.get("decision") != "app_dev":
        return {"ok": False, "error": "Phase 6에서 app_dev를 선택하지 않았음"}

    spec = bridge.get("deliverable_spec")
    if not spec:
        return {"ok": False, "error": "deliverable_spec 없음"}

    set_llm_context(
        db_path=db_path,
        project_id=project_id,
        run_id=artifact["run_id"],
        phase="phase_7",
    )

    try:
        result = run_phase_7_from_spec(
            deliverable_spec=spec,
            raw_input=project["raw_input"],
            db_path=db_path,
            project_id=project_id,
        )
    except Exception as exc:
        clear_llm_context()
        return {"ok": False, "error": f"Phase 7 실행 실패: {exc}"}

    update_project_phase(db_path, project_id, "phase_7_waiting_approval")
    clear_llm_context()

    return {
        "ok": result.status == "ok",
        "run_id": result.run_id,
        "approval_required": result.approval_required,
        "approval_status": result.approval_status,
        "plan": result.plan,
        "builder_output": result.builder_output,
        "reviewer_feedback": result.reviewer_feedback,
        "error": result.error,
    }


def handle_phase_7_approval(run_id: str, db_path: str, decision: str) -> Dict[str, Any]:
    from src.phases.phase_7_app_dev import handle_approval
    return handle_approval(db_path, run_id, decision)


def handle_phase_7_packet(run_id: str, db_path: str, base_dir: str = ".") -> Dict[str, Any]:
    from src.phases.phase_7_app_dev import handle_packet
    return handle_packet(db_path, run_id, base_dir)


def handle_phase_7_execution_result(
    run_id: str,
    db_path: str,
    changed_files: list,
    test_results: str,
    run_log: str,
) -> Dict[str, Any]:
    from src.phases.phase_7_app_dev import handle_execution_result
    return handle_execution_result(db_path, run_id, changed_files, test_results, run_log)


def handle_phase_7_verification(run_id: str, db_path: str) -> Dict[str, Any]:
    from src.phases.phase_7_app_dev import handle_verification
    return handle_verification(db_path, run_id)


def handle_phase_7_finalize(run_id: str, db_path: str) -> Dict[str, Any]:
    from src.phases.phase_7_app_dev import handle_finalize
    return handle_finalize(db_path, run_id)


# ---------------------------------------------------------------------------
# 프로젝트 조회
# ---------------------------------------------------------------------------

def get_project_status(project_id: str, db_path: str) -> Dict[str, Any]:
    """프로젝트 + 모든 artifact 통합 상태 반환."""
    project = load_project(db_path, project_id)
    if not project:
        return {"ok": False, "error": f"프로젝트 없음: {project_id}"}

    runs = list_project_runs(db_path, project_id)

    return {
        "ok": True,
        "project": project,
        "runs": runs,
        "error": None,
    }


def list_all_projects(db_path: str) -> Dict[str, Any]:
    """모든 프로젝트 리스트 (UI 페이지네이션용).

    _connect()를 경유해 스키마 초기화를 보장.
    """
    from src.store.artifact_store import _connect
    try:
        conn = _connect(db_path)
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC LIMIT 100"
        ).fetchall()
        conn.close()
        projects = [dict(r) for r in rows]
        return {"ok": True, "projects": projects, "error": None}
    except Exception as exc:
        return {"ok": False, "projects": [], "error": str(exc)}
