"""Initial Document Generator — evidence bundle 기반 기준 문서 초안 생성."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InitialDocument:
    """생성된 초안 문서."""
    title:    str
    sections: list[dict] = field(default_factory=list)  # [{heading, content}]
    source_bundle_id: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "sections": self.sections,
            "source_bundle_id": self.source_bundle_id,
        }


def generate_initial_document(
    goal: str,
    task_type: str,
    evidence_bundle: dict | None = None,
) -> InitialDocument:
    """
    evidence bundle을 받아 기준 문서 초안을 생성한다.
    v1 baseline: LLM 호출 없이 구조만 잡는다.
    TODO: OpenRouter 호출로 실제 생성
    """
    sections = [
        {"heading": "목적", "content": goal},
        {"heading": "범위", "content": f"task_type: {task_type}"},
        {"heading": "근거 요약", "content": _summarize_evidence(evidence_bundle)},
        {"heading": "제약 조건", "content": "TODO: 제약 조건 기술"},
    ]
    return InitialDocument(
        title=f"Initial Document — {goal[:50]}",
        sections=sections,
    )


def _summarize_evidence(bundle: dict | None) -> str:
    if not bundle:
        return "근거 없음 (리서치 미실행 또는 실패)"
    claims = bundle.get("claims", [])
    if not claims:
        return "근거 없음"
    lines = [f"- {c.get('claim', '?')} (출처: {c.get('source', '?')})" for c in claims[:5]]
    return "\n".join(lines)
