"""
v4 LangGraph 그래프 — Phase 7 앱개발 트랙 전용.

v3 전체 파이프라인(classify→research→document→...)은 Phase 0.5~6으로 대체됨.
이 파일은 Phase 7 (planner→builder→review→approval) 서브그래프만 포함.
"""
from __future__ import annotations

from typing import Optional
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# State 정의 — artifact_store 컬럼과 1:1 대응
# ---------------------------------------------------------------------------

class OrchestratorState(TypedDict, total=False):
    # 식별
    run_id:              str
    thread_id:           str
    raw_input:           str
    task_type:           str

    # 리서치 (v3 호환 필드, Phase 7 입력으로 전달 가능)
    research_bundle:     dict

    # 문서 계층 (v3 호환 필드)
    initial_document:    dict
    cross_audit_result:  dict
    canonical_doc:       dict
    canonical_frozen:    bool
    deliverable_spec:    dict

    # 계획
    slice_plan:          dict
    current_slice_index: int

    # planner / builder
    plan:                list[dict]
    plan_status:         str
    selected_models:     dict
    builder_output:      list[dict]
    builder_status:      str

    # 리뷰
    rule_check_result:   dict
    llm_review_result:   dict
    reviewer_feedback:   list[str]

    # 승인
    approval_required:   bool
    approval_status:     str
    approval_reason:     str

    # 패킷
    execution_packet:    dict
    packet_path:         str
    packet_status:       str

    # 실행 결과
    execution_result:    dict

    # 검증
    result_verification: dict
    spec_alignment:      dict

    # 최종
    final_summary:       str

    # 메타
    run_status:          str
    last_node:           str
    error:               Optional[str]

    # 내부 플래그
    doc_only_mode:       bool


# ---------------------------------------------------------------------------
# Phase 7 노드 — planner / builder / review_gate / approval_prepare
# ---------------------------------------------------------------------------

def planner_node(state: OrchestratorState) -> OrchestratorState:
    from src.planner.planner_service import run_planner
    result, model_id = run_planner(
        raw_input=state.get("raw_input", ""),
        task_type=state.get("task_type", ""),
    )
    selected_models = state.get("selected_models") or {}
    if model_id:
        selected_models = {**selected_models, "planner": model_id}
    return {
        **state,
        **result.to_state_dict(),
        "selected_models": selected_models,
        "last_node": "planner",
    }


def builder_node(state: OrchestratorState) -> OrchestratorState:
    from src.builder.builder_service import run_builder
    result, model_id = run_builder(
        raw_input=state.get("raw_input", ""),
        task_type=state.get("task_type", ""),
        plan=state.get("plan") or [],
    )
    selected_models = state.get("selected_models") or {}
    if model_id:
        selected_models = {**selected_models, "builder": model_id}
    return {
        **state,
        **result.to_state_dict(),
        "selected_models": selected_models,
        "last_node": "builder",
    }


def review_gate_node(state: OrchestratorState) -> OrchestratorState:
    from src.reviewer.review_gate import run_review_gate
    result = run_review_gate(
        plan=state.get("plan") or [],
        builder_output=state.get("builder_output") or [],
        deliverable_spec=state.get("deliverable_spec"),
    )
    return {
        **state,
        "rule_check_result": result.rule_result.to_dict() if result.rule_result else None,
        "llm_review_result": result.llm_result.to_dict() if result.llm_result else None,
        "reviewer_feedback": result.feedback,
        "last_node": "review_gate",
    }


def approval_prepare_node(state: OrchestratorState) -> OrchestratorState:
    return {
        **state,
        "approval_required": True,
        "approval_status": "pending",
        "approval_reason": "requires_user_approval",
        "run_status": "waiting_approval",
        "last_node": "approval_prepare",
    }


# ---------------------------------------------------------------------------
# Phase 7 그래프 — v4 앱개발 트랙
# spec → planner → builder → review_gate → approval_prepare → END
# ---------------------------------------------------------------------------

def build_phase_7_graph():
    """
    Phase 7 · 앱개발 실행용 서브그래프.

    입력 state (Phase 6 BridgeDecision.deliverable_spec 기반):
      - raw_input: str
      - deliverable_spec: dict
      - task_type: str

    출력 state:
      - plan, builder_output, reviewer_feedback
      - approval_required=True, approval_status="pending"
      - run_status="waiting_approval"
    """
    graph = StateGraph(OrchestratorState)

    graph.add_node("planner",          planner_node)
    graph.add_node("builder",          builder_node)
    graph.add_node("review_gate",      review_gate_node)
    graph.add_node("approval_prepare", approval_prepare_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner",          "builder")
    graph.add_edge("builder",          "review_gate")
    graph.add_edge("review_gate",      "approval_prepare")
    graph.add_edge("approval_prepare", END)

    return graph.compile()
