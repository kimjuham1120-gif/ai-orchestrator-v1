"""Final Deliverable Spec — canonical doc에서 실행 가능한 인도물 명세 추출."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DeliverableSpec:
    """최종 인도물 명세."""
    goal:              str
    scope:             str
    acceptance_criteria: list[str] = field(default_factory=list)
    constraints:       list[str] = field(default_factory=list)
    target_files:      list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "scope": self.scope,
            "acceptance_criteria": self.acceptance_criteria,
            "constraints": self.constraints,
            "target_files": self.target_files,
        }


def build_deliverable_spec(canonical_doc: dict, goal: str) -> DeliverableSpec:
    """
    확정 문서에서 인도물 명세를 생성한다.
    v1 baseline: 문서 섹션에서 단순 추출.
    TODO: LLM으로 정교한 명세 추출
    """
    doc_content = canonical_doc.get("document", {})
    sections = doc_content.get("sections", [])

    scope = ""
    constraints = []
    for sec in sections:
        heading = sec.get("heading", "").lower()
        content = sec.get("content", "")
        if "범위" in heading or "scope" in heading:
            scope = content
        elif "제약" in heading or "constraint" in heading:
            constraints.append(content)

    return DeliverableSpec(
        goal=goal,
        scope=scope or "전체",
        acceptance_criteria=["모든 테스트 통과", "spec alignment 검증 통과"],
        constraints=constraints or ["scope 이탈 금지"],
    )
