"""Cross-Audit Loop — GPT/Claude/Gemini 역할 분리 감사.

v1 baseline: 규칙 기반 간이 감사만 수행. LLM 감사는 TODO.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AuditFinding:
    """단일 감사 결과."""
    auditor:  str   # "rule" | "gpt" | "claude" | "gemini"
    severity: str   # "pass" | "warning" | "error"
    message:  str

    def to_dict(self) -> dict:
        return {"auditor": self.auditor, "severity": self.severity, "message": self.message}


@dataclass
class CrossAuditResult:
    """감사 루프 전체 결과."""
    findings:  list[AuditFinding] = field(default_factory=list)
    passed:    bool = True
    iteration: int = 1

    def to_dict(self) -> dict:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "passed": self.passed,
            "iteration": self.iteration,
        }


def run_cross_audit(document: dict, max_iterations: int = 3) -> CrossAuditResult:
    """
    문서에 대해 교차 감사를 수행한다.
    v1 baseline: 빈 섹션 체크만. LLM 감사는 TODO.
    """
    findings: list[AuditFinding] = []

    sections = document.get("sections", [])
    if not sections:
        findings.append(AuditFinding(
            auditor="rule", severity="error", message="문서에 섹션이 없음",
        ))
    else:
        for sec in sections:
            content = sec.get("content", "").strip()
            if not content or content.startswith("TODO"):
                findings.append(AuditFinding(
                    auditor="rule",
                    severity="warning",
                    message=f"섹션 '{sec.get('heading', '?')}' 내용이 비어있거나 TODO 상태",
                ))

    passed = all(f.severity != "error" for f in findings)
    return CrossAuditResult(findings=findings, passed=passed)
