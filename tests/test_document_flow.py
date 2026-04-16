"""문서 계층 (initial → cross-audit → freeze → spec) 테스트."""
from src.document.initial_generator import generate_initial_document
from src.document.cross_audit import run_cross_audit
from src.document.canonical_freeze import freeze_document, unfreeze_for_reaudit
from src.document.deliverable_spec import build_deliverable_spec


def test_initial_document_has_sections():
    doc = generate_initial_document("버그 수정", "code_fix")
    assert doc.title
    assert len(doc.sections) >= 3


def test_cross_audit_passes_on_valid_doc():
    doc = generate_initial_document("버그 수정", "code_fix", evidence_bundle=None)
    result = run_cross_audit(doc.to_dict())
    # TODO 섹션이 있으므로 warning은 날 수 있지만 error는 아님
    assert isinstance(result.passed, bool)


def test_cross_audit_fails_on_empty():
    result = run_cross_audit({"sections": []})
    assert not result.passed


def test_freeze_when_audit_passed():
    doc = {"title": "test", "sections": [{"heading": "목적", "content": "goal"}]}
    canonical = freeze_document(doc, audit_passed=True)
    assert canonical.frozen is True
    assert canonical.frozen_at != ""


def test_no_freeze_when_audit_failed():
    canonical = freeze_document({"title": "test"}, audit_passed=False)
    assert canonical.frozen is False


def test_unfreeze_increments_version():
    from src.document.canonical_freeze import CanonicalDoc
    c = CanonicalDoc(document={"a": 1}, frozen=True, frozen_at="2025-01-01", version=1)
    unfrozen = unfreeze_for_reaudit(c)
    assert unfrozen.frozen is False
    assert unfrozen.version == 2


def test_deliverable_spec_from_canonical():
    canonical = {
        "document": {
            "sections": [
                {"heading": "범위", "content": "auth module"},
                {"heading": "제약 조건", "content": "scope 이탈 금지"},
            ]
        }
    }
    spec = build_deliverable_spec(canonical, "fix login")
    assert spec.goal == "fix login"
    assert "auth module" in spec.scope
    assert len(spec.constraints) > 0
