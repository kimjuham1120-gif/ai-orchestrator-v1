"""고유 ID 생성 유틸리티."""
from __future__ import annotations

import uuid


def generate_thread_id() -> str:
    return f"thread-{uuid.uuid4().hex[:8]}"


def generate_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:8]}"


def generate_artifact_id(prefix: str = "art") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
