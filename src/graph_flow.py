"""
v1 LangGraph 그래프 — 문서고정 중심 상위 계층 + 역산 실행 구조.

노드 흐름:
  classify → research_route → evidence_bundle → initial_doc
  → cross_audit → canonical_freeze → (doc_only_stop 가능)
  → deliverable_spec → backward_plan → slice_queue
  → planner → builder → review_gate → approval_prepare
  → (approval 후) packet_generate → (Cursor 수동 실행)
  → result_verify → spec_align → (pass?) → more_slices?
  → finalize

상태명은 v1 SSOT에 따라 artifact_store 컬럼명과 일치시킨다.
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

    # 리서치
    research_bundle:     dict          # EvidenceBundle.to_dict()

    # 문서 계층
    initial_document:    dict
    cross_audit_result:  dict
    canonical_doc:       dict
    canonical_frozen:    bool
    deliverable_spec:    dict

    # 계획
    slice_plan:          dict          # SlicePlan.to_dict()
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
# 노드 구현
# ---------------------------------------------------------------------------

def classify_node(state: OrchestratorState) -> OrchestratorState:
    from src.classifier.classifier import classify_request
    task_type = classify_request(state.get("raw_input", ""))
    return {**state, "task_type": task_type, "run_status": "classified", "last_node": "classify"}


def research_route_node(state: OrchestratorState) -> OrchestratorState:
    from src.research.router import run_research
    bundle = run_research(state.get("raw_input", ""), state.get("task_type", ""))
    return {**state, "research_bundle": bundle.to_dict(), "last_node": "research_route"}


def evidence_bundle_node(state: OrchestratorState) -> OrchestratorState:
    """research_route에서 이미 번들 생성 완료. 여기서는 상태 전이만."""
    return {**state, "last_node": "evidence_bundle"}


def initial_doc_node(state: OrchestratorState) -> OrchestratorState:
    from src.document.initial_generator import generate_initial_document
    doc = generate_initial_document(
        goal=state.get("raw_input", ""),
        task_type=state.get("task_type", ""),
        evidence_bundle=state.get("research_bundle"),
    )
    return {**state, "initial_document": doc.to_dict(), "last_node": "initial_doc"}


def cross_audit_node(state: OrchestratorState) -> OrchestratorState:
    from src.document.cross_audit import run_cross_audit
    doc = state.get("initial_document", {})
    result = run_cross_audit(doc)
    return {**state, "cross_audit_result": result.to_dict(), "last_node": "cross_audit"}


def canonical_freeze_node(state: OrchestratorState) -> OrchestratorState:
    from src.document.canonical_freeze import freeze_document
    doc = state.get("initial_document", {})
    audit = state.get("cross_audit_result", {})
    canonical = freeze_document(doc, audit.get("passed", False))
    return {
        **state,
        "canonical_doc": canonical.to_dict(),
        "canonical_frozen": canonical.frozen,
        "last_node": "canonical_freeze",
    }


def deliverable_spec_node(state: OrchestratorState) -> OrchestratorState:
    from src.document.deliverable_spec import build_deliverable_spec
    spec = build_deliverable_spec(
        canonical_doc=state.get("canonical_doc", {}),
        goal=state.get("raw_input", ""),
    )
    return {**state, "deliverable_spec": spec.to_dict(), "last_node": "deliverable_spec"}


def backward_plan_node(state: OrchestratorState) -> OrchestratorState:
    from src.planning.backward_planner import build_slice_plan
    plan = build_slice_plan(
        deliverable_spec=state.get("deliverable_spec", {}),
        plan_steps=state.get("plan"),
    )
    return {
        **state,
        "slice_plan": plan.to_dict(),
        "current_slice_index": 0,
        "last_node": "backward_plan",
    }


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


def unsupported_node(state: OrchestratorState) -> OrchestratorState:
    return {
        **state,
        "approval_required": False,
        "approval_status": "not_needed",
        "run_status": "failed",
        "error": "unsupported_task_type",
        "last_node": "unsupported",
    }


def doc_only_stop_node(state: OrchestratorState) -> OrchestratorState:
    """문서 고정까지만 수행하고 중단 (resume 가능)."""
    return {
        **state,
        "run_status": "doc_frozen",
        "last_node": "doc_only_stop",
    }


# ---------------------------------------------------------------------------
# 라우터
# ---------------------------------------------------------------------------

def route_after_classify(state: OrchestratorState) -> str:
    task_type = state.get("task_type", "unsupported")
    if task_type == "unsupported":
        return "unsupported"
    return "research_route"


def route_after_canonical_freeze(state: OrchestratorState) -> str:
    if state.get("doc_only_mode"):
        return "doc_only_stop"
    return "deliverable_spec"


# ---------------------------------------------------------------------------
# 그래프 조립
# ---------------------------------------------------------------------------

def build_graph():
    graph = StateGraph(OrchestratorState)

    # 노드 등록
    graph.add_node("classify",          classify_node)
    graph.add_node("unsupported",       unsupported_node)
    graph.add_node("research_route",    research_route_node)
    graph.add_node("evidence_bundle",   evidence_bundle_node)
    graph.add_node("initial_doc",       initial_doc_node)
    graph.add_node("cross_audit",       cross_audit_node)
    graph.add_node("canonical_freeze",  canonical_freeze_node)
    graph.add_node("doc_only_stop",     doc_only_stop_node)
    graph.add_node("deliverable_spec",  deliverable_spec_node)
    graph.add_node("backward_plan",     backward_plan_node)
    graph.add_node("planner",           planner_node)
    graph.add_node("builder",           builder_node)
    graph.add_node("review_gate",       review_gate_node)
    graph.add_node("approval_prepare",  approval_prepare_node)

    # 엣지
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", route_after_classify, {
        "unsupported":    "unsupported",
        "research_route": "research_route",
    })
    graph.add_edge("unsupported",      END)
    graph.add_edge("research_route",   "evidence_bundle")
    graph.add_edge("evidence_bundle",  "initial_doc")
    graph.add_edge("initial_doc",      "cross_audit")
    graph.add_edge("cross_audit",      "canonical_freeze")
    graph.add_conditional_edges("canonical_freeze", route_after_canonical_freeze, {
        "doc_only_stop":   "doc_only_stop",
        "deliverable_spec": "deliverable_spec",
    })
    graph.add_edge("doc_only_stop",    END)
    graph.add_edge("deliverable_spec", "backward_plan")
    graph.add_edge("backward_plan",    "planner")
    graph.add_edge("planner",          "builder")
    graph.add_edge("builder",          "review_gate")
    graph.add_edge("review_gate",      "approval_prepare")
    graph.add_edge("approval_prepare", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Resume 그래프 — doc_frozen 상태에서 실행 계획으로 진행
# deliverable_spec → backward_plan → planner → builder → review_gate → approval_prepare
# ---------------------------------------------------------------------------

def build_resume_from_doc_graph():
    """doc_frozen 상태에서 이어서 실행할 서브 그래프."""
    graph = StateGraph(OrchestratorState)

    graph.add_node("deliverable_spec",  deliverable_spec_node)
    graph.add_node("backward_plan",     backward_plan_node)
    graph.add_node("planner",           planner_node)
    graph.add_node("builder",           builder_node)
    graph.add_node("review_gate",       review_gate_node)
    graph.add_node("approval_prepare",  approval_prepare_node)

    graph.add_edge(START, "deliverable_spec")
    graph.add_edge("deliverable_spec", "backward_plan")
    graph.add_edge("backward_plan",    "planner")
    graph.add_edge("planner",          "builder")
    graph.add_edge("builder",          "review_gate")
    graph.add_edge("review_gate",      "approval_prepare")
    graph.add_edge("approval_prepare", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Slice 반복 그래프 — 현재 slice에 대해 planner → builder → review
# ---------------------------------------------------------------------------

def build_slice_iteration_graph():
    """단일 slice 실행용 서브 그래프."""
    graph = StateGraph(OrchestratorState)

    graph.add_node("planner",           planner_node)
    graph.add_node("builder",           builder_node)
    graph.add_node("review_gate",       review_gate_node)
    graph.add_node("approval_prepare",  approval_prepare_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner",          "builder")
    graph.add_edge("builder",          "review_gate")
    graph.add_edge("review_gate",      "approval_prepare")
    graph.add_edge("approval_prepare", END)

    return graph.compile()
