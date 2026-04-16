"""
Artifact Store — v1 상태 저장의 SSOT.

모든 artifact 필드는 동일한 규칙으로 직렬화/역직렬화한다:
  - Python dict/list → JSON TEXT 로 저장
  - DB에서 읽을 때 → json.loads 로 복원
  - None → NULL (DB) / None (Python)
  - 빈 문자열 → None 으로 취급

artifact 종류 (10종):
  request, research_bundle, canonical_doc, deliverable_spec,
  slice_plan, patch, review, approval_status,
  execution_result, final_summary
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 공통 직렬화 규칙 — 모든 필드에 동일하게 적용
# ---------------------------------------------------------------------------

def serialize(value: Any) -> Optional[str]:
    """Python 객체 → DB TEXT. None이면 None 반환."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    return json.dumps(value, ensure_ascii=False)


def deserialize(value: Optional[str]) -> Any:
    """DB TEXT → Python 객체. None/빈문자열이면 None 반환."""
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value  # 순수 문자열은 그대로


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Artifact 테이블 DDL
# ---------------------------------------------------------------------------

_ARTIFACT_COLUMNS: List[tuple[str, str]] = [
    # 식별자
    ("run_id",              "TEXT"),
    ("thread_id",           "TEXT"),

    # 입력
    ("raw_input",           "TEXT"),
    ("task_type",           "TEXT"),

    # 리서치
    ("research_bundle",     "TEXT"),   # JSON

    # 문서 계층
    ("initial_document",    "TEXT"),   # JSON
    ("cross_audit_result",  "TEXT"),   # JSON
    ("canonical_doc",       "TEXT"),   # JSON
    ("canonical_frozen",    "INTEGER"),  # 0/1
    ("deliverable_spec",    "TEXT"),   # JSON

    # 계획
    ("slice_plan",          "TEXT"),   # JSON — list of slices
    ("current_slice_index", "INTEGER"),

    # planner/builder
    ("plan",                "TEXT"),   # JSON
    ("plan_status",         "TEXT"),
    ("selected_models",     "TEXT"),   # JSON
    ("builder_output",      "TEXT"),   # JSON
    ("builder_status",      "TEXT"),

    # 리뷰
    ("rule_check_result",   "TEXT"),   # JSON — 1차
    ("llm_review_result",   "TEXT"),   # JSON — 2차
    ("reviewer_feedback",   "TEXT"),   # JSON — 통합

    # 승인
    ("approval_required",   "INTEGER"),
    ("approval_status",     "TEXT"),
    ("approval_reason",     "TEXT"),
    ("approval_actor",      "TEXT"),
    ("approval_timestamp",  "TEXT"),

    # 패킷
    ("execution_packet",    "TEXT"),   # JSON
    ("packet_path",         "TEXT"),
    ("packet_status",       "TEXT"),

    # 실행 결과
    ("execution_result",    "TEXT"),   # JSON

    # 검증
    ("result_verification", "TEXT"),   # JSON
    ("spec_alignment",      "TEXT"),   # JSON

    # 최종
    ("final_summary",       "TEXT"),

    # 메타
    ("run_status",          "TEXT"),
    ("last_node",           "TEXT"),
    ("error",               "TEXT"),
    ("created_at",          "TEXT"),
    ("updated_at",          "TEXT"),
]

# 항상 compact에서 유지할 키
_ALWAYS_INCLUDE = frozenset({"error", "run_id", "thread_id", "run_status"})

# JSON 직렬화 대상 컬럼
_JSON_COLUMNS = frozenset({
    "research_bundle", "initial_document", "cross_audit_result",
    "canonical_doc", "deliverable_spec", "slice_plan",
    "plan", "selected_models", "builder_output",
    "rule_check_result", "llm_review_result", "reviewer_feedback",
    "execution_packet", "execution_result",
    "result_verification", "spec_alignment",
})

# BOOLEAN 컬럼 (INTEGER 0/1 ↔ bool)
_BOOL_COLUMNS = frozenset({"approval_required", "canonical_frozen"})


# ---------------------------------------------------------------------------
# 테이블 생성 / 마이그레이션
# ---------------------------------------------------------------------------

def _ensure_tables(conn: sqlite3.Connection) -> None:
    cols_ddl = ",\n".join(f"    {name} {typ}" for name, typ in _ARTIFACT_COLUMNS)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {cols_ddl},
            UNIQUE(run_id)
        )
    """)
    # 마이그레이션: 누락 컬럼 추가
    existing = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
    for col_name, col_type in _ARTIFACT_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE artifacts ADD COLUMN {col_name} {col_type}")
    conn.commit()


# ---------------------------------------------------------------------------
# 정규화: Python → DB
# ---------------------------------------------------------------------------

def _normalize_for_db(state: Dict[str, Any]) -> Dict[str, Any]:
    """모든 필드를 일관된 규칙으로 직렬화."""
    result: Dict[str, Any] = {}
    valid_cols = {name for name, _ in _ARTIFACT_COLUMNS}
    for key, value in state.items():
        if key not in valid_cols:
            continue
        if key in _JSON_COLUMNS:
            result[key] = serialize(value)
        elif key in _BOOL_COLUMNS:
            result[key] = None if value is None else int(bool(value))
        else:
            result[key] = value
    return result


def _denormalize_from_db(row: sqlite3.Row) -> Dict[str, Any]:
    """모든 필드를 일관된 규칙으로 역직렬화."""
    data = dict(row)
    for key in _JSON_COLUMNS:
        if key in data:
            data[key] = deserialize(data.get(key))
    for key in _BOOL_COLUMNS:
        if key in data:
            v = data[key]
            data[key] = None if v is None else bool(v)
    return data


def _compact(data: Dict[str, Any]) -> Dict[str, Any]:
    """None 값 제거 (ALWAYS_INCLUDE 제외)."""
    return {
        k: v for k, v in data.items()
        if k in _ALWAYS_INCLUDE or (v is not None and v != [] and v != {})
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def save_artifact(db_path: str, state: Dict[str, Any]) -> None:
    """artifact 저장. run_id 기준 UPSERT."""
    norm = _normalize_for_db(state)
    norm.setdefault("created_at", utc_now_iso())
    norm["updated_at"] = utc_now_iso()

    if not norm.get("run_id"):
        raise ValueError("run_id is required")

    with sqlite3.connect(db_path) as conn:
        _ensure_tables(conn)
        cols = list(norm.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        col_names = ", ".join(cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "run_id")
        conn.execute(
            f"INSERT INTO artifacts ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT(run_id) DO UPDATE SET {updates}",
            norm,
        )
        conn.commit()


def load_artifact(
    db_path: str,
    run_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """artifact 조회. run_id 또는 thread_id 기준."""
    if not run_id and not thread_id:
        raise ValueError("run_id or thread_id is required")

    with sqlite3.connect(db_path) as conn:
        _ensure_tables(conn)
        conn.row_factory = sqlite3.Row
        if run_id:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE run_id = ?", (run_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE thread_id = ? ORDER BY id DESC LIMIT 1",
                (thread_id,),
            ).fetchone()

    if row is None:
        return None
    return _compact(_denormalize_from_db(row))


def update_artifact(
    db_path: str,
    run_id: str,
    updates: Dict[str, Any],
) -> None:
    """artifact 부분 업데이트. 지정한 필드만 갱신."""
    norm = _normalize_for_db(updates)
    norm["updated_at"] = utc_now_iso()

    with sqlite3.connect(db_path) as conn:
        _ensure_tables(conn)
        set_clause = ", ".join(f"{k} = ?" for k in norm)
        values = list(norm.values()) + [run_id]
        conn.execute(
            f"UPDATE artifacts SET {set_clause} WHERE run_id = ?",
            values,
        )
        conn.commit()


# ---------------------------------------------------------------------------
# 편의 함수 — 특정 상태 전이
# ---------------------------------------------------------------------------

def update_approval(
    db_path: str,
    run_id: str,
    status: str,
    reason: str = "",
    actor: str = "user",
) -> None:
    update_artifact(db_path, run_id, {
        "approval_status": status,
        "approval_reason": reason,
        "approval_actor": actor,
        "approval_timestamp": utc_now_iso(),
        "run_status": status,  # approved/rejected
    })


def update_execution_result(
    db_path: str,
    run_id: str,
    changed_files: list,
    test_results: str,
    run_log: str,
) -> None:
    update_artifact(db_path, run_id, {
        "execution_result": {
            "changed_files": changed_files,
            "test_results": test_results,
            "run_log": run_log,
        },
        "run_status": "execution_result_received",
    })


def update_final_summary(
    db_path: str,
    run_id: str,
    summary: str,
) -> None:
    update_artifact(db_path, run_id, {
        "final_summary": summary,
        "run_status": "completed",
    })
