"""
Artifact Store — SQLite 기반 단일 진실 원천(SSOT).

v4 확장 (Day 113~):
  - projects 테이블 추가 (프로젝트 단위 관리)
  - artifacts 테이블에 v4 컬럼 11개 추가 (모두 JSON, NULL 허용)
  - 기존 v3 API 시그니처 전부 유지 (하위호환)
  - 신규 v4 API는 같은 파일 하단에 추가

JSON 컬럼 직렬화 규칙:
- dict / list  → json.dumps (str)
- None         → NULL
- bool         → INTEGER (0/1)
- 빈 문자열   → NULL
- 기타 str     → 그대로

스키마 변경 원칙:
- 기존 컬럼 전부 유지
- 새 컬럼은 ALTER TABLE로 추가 (기존 데이터 보존)
- 마이그레이션은 멱등성 보장 (여러 번 실행해도 안전)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 시간 헬퍼 (v1부터 사용 — 하위호환 필수)
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """현재 UTC 시각을 ISO 8601 문자열로 반환."""
    return datetime.now(timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# 직렬화 / 역직렬화
# ---------------------------------------------------------------------------

# v3 기존 JSON 컬럼
_JSON_COLS_V3 = {
    "research_bundle", "initial_document", "cross_audit_result",
    "canonical_doc", "deliverable_spec", "slice_plan",
    "plan", "selected_models", "builder_output",
    "rule_check_result", "llm_review_result", "reviewer_feedback",
    "execution_result", "execution_packet",
    "result_verification", "spec_alignment",
}

# v4 신규 JSON 컬럼
_JSON_COLS_V4 = {
    "feasibility_result",   # Phase 0.5
    "subtopics",            # Phase 1
    "parallel_research",    # Phase 2
    "base_info_doc",        # Phase 3a
    "target_doc",           # Phase 3b
    "cross_audit_v4",       # Phase 4
    "doc_versions",         # Phase 5
    "feedback_history",     # Phase 5
}

# 전체 JSON 컬럼 (v3 + v4)
_JSON_COLS = _JSON_COLS_V3 | _JSON_COLS_V4


def serialize(value: Any) -> Optional[str]:
    """Python 값 → DB 저장용 문자열."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value  # bool, int 등은 그대로


def deserialize(value: Any) -> Any:
    """DB 문자열 → Python 값."""
    if value is None:
        return None
    if isinstance(value, str):
        if not value:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


# ---------------------------------------------------------------------------
# DDL — v4 스키마
# ---------------------------------------------------------------------------

# artifacts 테이블 (v3 기존 + v4 신규 컬럼)
_DDL_ARTIFACTS = """
CREATE TABLE IF NOT EXISTS artifacts (
    run_id               TEXT PRIMARY KEY,
    thread_id            TEXT,
    raw_input            TEXT,
    task_type            TEXT,

    research_bundle      TEXT,
    initial_document     TEXT,
    cross_audit_result   TEXT,
    canonical_doc        TEXT,
    canonical_frozen     INTEGER,
    deliverable_spec     TEXT,

    slice_plan           TEXT,
    current_slice_index  INTEGER DEFAULT 0,

    plan                 TEXT,
    plan_status          TEXT,
    selected_models      TEXT,
    builder_output       TEXT,
    builder_status       TEXT,

    rule_check_result    TEXT,
    llm_review_result    TEXT,
    reviewer_feedback    TEXT,

    approval_required    INTEGER,
    approval_status      TEXT,
    approval_reason      TEXT,

    execution_packet     TEXT,
    packet_path          TEXT,
    packet_status        TEXT,

    execution_result     TEXT,

    result_verification  TEXT,
    spec_alignment       TEXT,

    final_summary        TEXT,
    run_status           TEXT,
    last_node            TEXT,
    error                TEXT,

    -- v4 신규 컬럼 (모두 NULL 허용)
    project_id           TEXT,
    phase                TEXT,
    feasibility_result   TEXT,
    subtopics            TEXT,
    parallel_research    TEXT,
    base_info_doc        TEXT,
    target_doc           TEXT,
    cross_audit_v4       TEXT,
    doc_versions         TEXT,
    feedback_history     TEXT,
    bridge_decision      TEXT
)
"""

# projects 테이블 (v4 신규)
_DDL_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    project_id      TEXT PRIMARY KEY,
    title           TEXT,
    raw_input       TEXT,
    created_at      TEXT,
    updated_at      TEXT,
    current_phase   TEXT,
    status          TEXT
)
"""

# v4 신규 컬럼 리스트 (마이그레이션용)
_V4_NEW_COLUMNS = [
    ("project_id",         "TEXT"),
    ("phase",              "TEXT"),
    ("feasibility_result", "TEXT"),
    ("subtopics",          "TEXT"),
    ("parallel_research",  "TEXT"),
    ("base_info_doc",      "TEXT"),
    ("target_doc",         "TEXT"),
    ("cross_audit_v4",     "TEXT"),
    ("doc_versions",       "TEXT"),
    ("feedback_history",   "TEXT"),
    ("bridge_decision",    "TEXT"),
]


def _ensure_v4_columns(conn: sqlite3.Connection) -> None:
    """
    기존 v3 DB에 v4 컬럼을 ALTER TABLE로 추가.
    이미 있는 컬럼은 건너뜀 (멱등성).
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
    for col_name, col_type in _V4_NEW_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE artifacts ADD COLUMN {col_name} {col_type}")
    conn.commit()


def _connect(db_path: str) -> sqlite3.Connection:
    """
    DB 연결 + 스키마 보장.
    - 신규 DB: CREATE TABLE 실행
    - 기존 v3 DB: ALTER TABLE로 v4 컬럼 추가
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_DDL_ARTIFACTS)
    conn.execute(_DDL_PROJECTS)
    _ensure_v4_columns(conn)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# v3 기존 API (하위호환 유지 — 시그니처 변경 없음)
# ---------------------------------------------------------------------------

def save_artifact(db_path: str, artifact: Dict[str, Any]) -> None:
    """artifact dict를 DB에 INSERT (run_id 중복 시 덮어쓰기)."""
    conn = _connect(db_path)
    cols = list(artifact.keys())
    vals = []
    for col, val in artifact.items():
        if col in _JSON_COLS:
            vals.append(serialize(val))
        elif isinstance(val, bool):
            vals.append(int(val))
        else:
            vals.append(val)

    placeholders = ", ".join("?" * len(cols))
    col_names = ", ".join(cols)
    conn.execute(
        f"INSERT OR REPLACE INTO artifacts ({col_names}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()
    conn.close()


def load_artifact(
    db_path: str,
    run_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """run_id 또는 thread_id로 artifact 로드."""
    conn = _connect(db_path)
    if run_id:
        row = conn.execute(
            "SELECT * FROM artifacts WHERE run_id = ?", (run_id,)
        ).fetchone()
    elif thread_id:
        row = conn.execute(
            "SELECT * FROM artifacts WHERE thread_id = ?", (thread_id,)
        ).fetchone()
    else:
        conn.close()
        return None

    if not row:
        conn.close()
        return None

    result: Dict[str, Any] = {}
    for key in row.keys():
        val = row[key]
        if key in _JSON_COLS:
            result[key] = deserialize(val)
        elif key in ("approval_required", "canonical_frozen") and val is not None:
            result[key] = bool(val)
        else:
            result[key] = val

    conn.close()
    return result


def update_artifact(db_path: str, run_id: str, updates: Dict[str, Any]) -> None:
    """특정 컬럼만 업데이트."""
    if not updates:
        return
    conn = _connect(db_path)
    set_clauses = []
    vals = []
    for col, val in updates.items():
        set_clauses.append(f"{col} = ?")
        if col in _JSON_COLS:
            vals.append(serialize(val))
        elif isinstance(val, bool):
            vals.append(int(val))
        else:
            vals.append(val)
    vals.append(run_id)
    conn.execute(
        f"UPDATE artifacts SET {', '.join(set_clauses)} WHERE run_id = ?",
        vals,
    )
    conn.commit()
    conn.close()


def update_approval(
    db_path: str,
    run_id: str,
    status: str,
    reason: str = "",
) -> None:
    update_artifact(db_path, run_id, {
        "approval_status": status,
        "approval_reason": reason,
        "run_status": status,
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


def update_final_summary(db_path: str, run_id: str, summary: str) -> None:
    update_artifact(db_path, run_id, {
        "final_summary": summary,
        "run_status": "completed",
    })


# ---------------------------------------------------------------------------
# v4 신규 API — projects 테이블
# ---------------------------------------------------------------------------

def save_project(db_path: str, project: Dict[str, Any]) -> None:
    """
    프로젝트 저장 (project_id 중복 시 덮어쓰기).

    필수 키: project_id
    선택 키: title, raw_input, created_at, updated_at, current_phase, status
    """
    if "project_id" not in project:
        raise ValueError("project dict must contain 'project_id'")

    conn = _connect(db_path)
    cols = list(project.keys())
    vals = [project[c] for c in cols]
    placeholders = ", ".join("?" * len(cols))
    col_names = ", ".join(cols)
    conn.execute(
        f"INSERT OR REPLACE INTO projects ({col_names}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()
    conn.close()


def load_project(db_path: str, project_id: str) -> Optional[Dict[str, Any]]:
    """project_id로 프로젝트 로드."""
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT * FROM projects WHERE project_id = ?", (project_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {key: row[key] for key in row.keys()}


def update_project(
    db_path: str,
    project_id: str,
    updates: Dict[str, Any],
) -> None:
    """프로젝트 특정 컬럼만 업데이트."""
    if not updates:
        return
    conn = _connect(db_path)
    set_clauses = [f"{col} = ?" for col in updates.keys()]
    vals = list(updates.values()) + [project_id]
    conn.execute(
        f"UPDATE projects SET {', '.join(set_clauses)} WHERE project_id = ?",
        vals,
    )
    conn.commit()
    conn.close()


def list_project_runs(db_path: str, project_id: str) -> List[Dict[str, Any]]:
    """
    해당 프로젝트에 속한 모든 artifact (run) 를 Phase 순서로 반환.

    1 프로젝트 = N run 구조에서 프로젝트별 전체 run 이력 조회용.
    """
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT * FROM artifacts WHERE project_id = ? ORDER BY rowid ASC",
        (project_id,),
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        item: Dict[str, Any] = {}
        for key in row.keys():
            val = row[key]
            if key in _JSON_COLS:
                item[key] = deserialize(val)
            elif key in ("approval_required", "canonical_frozen") and val is not None:
                item[key] = bool(val)
            else:
                item[key] = val
        results.append(item)
    return results


def update_project_phase(
    db_path: str,
    project_id: str,
    current_phase: str,
    status: str = "in_progress",
) -> None:
    """프로젝트의 현재 Phase 및 상태 갱신."""
    update_project(db_path, project_id, {
        "current_phase": current_phase,
        "status": status,
        "updated_at": utc_now_iso(),
    })
