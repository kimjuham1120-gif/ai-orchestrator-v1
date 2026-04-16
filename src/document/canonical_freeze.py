"""Canonical Document Freeze — 기준 문서 확정.

freeze 후에는 re-audit 경로를 통해서만 변경 가능.
"""
from __future__ import annotations

from dataclasses import dataclass
from src.store.artifact_store import utc_now_iso


@dataclass
class CanonicalDoc:
    """확정된 기준 문서."""
    document: dict
    frozen: bool = False
    frozen_at: str = ""
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "document": self.document,
            "frozen": self.frozen,
            "frozen_at": self.frozen_at,
            "version": self.version,
        }


def freeze_document(document: dict, audit_passed: bool) -> CanonicalDoc:
    """감사 통과 시 문서를 확정한다."""
    if not audit_passed:
        return CanonicalDoc(document=document, frozen=False)
    return CanonicalDoc(
        document=document,
        frozen=True,
        frozen_at=utc_now_iso(),
    )


def unfreeze_for_reaudit(canonical: CanonicalDoc) -> CanonicalDoc:
    """re-audit 위해 동결 해제. 버전 증가."""
    return CanonicalDoc(
        document=canonical.document,
        frozen=False,
        version=canonical.version + 1,
    )
