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
    "bridge_decision",      # Phase 6
    "referenced_context",   # Step 15: 업로드된 기획문서 묶음
    "todo_list",            # Step 15: 작업 단위 목록
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
    bridge_decision      TEXT,
    template_text        TEXT,

    -- Step 15 (Phase A): 점진적 앱개발
    project_type         TEXT,
    referenced_context   TEXT,
    todo_list            TEXT,
    current_todo_idx     INTEGER DEFAULT 0,
    todo_status          TEXT,
    preview_port         INTEGER
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
    status          TEXT,
    project_type    TEXT DEFAULT 'doc_generation'
)
"""

# llm_calls 테이블 (Step 14-1 신규 — 비용·토큰 추적)
_DDL_LLM_CALLS = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id         TEXT,
    run_id             TEXT,
    phase              TEXT,
    model              TEXT,
    prompt_tokens      INTEGER DEFAULT 0,
    completion_tokens  INTEGER DEFAULT 0,
    total_tokens       INTEGER DEFAULT 0,
    cost_usd           REAL    DEFAULT 0.0,
    cached             INTEGER DEFAULT 0,
    duration_ms        INTEGER DEFAULT 0,
    status             TEXT    DEFAULT 'success',
    error              TEXT,
    created_at         TEXT
)
"""

# llm_calls 인덱스 (집계·조회 최적화)
_INDEXES_LLM_CALLS = [
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_project  ON llm_calls(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_run      ON llm_calls(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_created  ON llm_calls(created_at)",
]

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
    ("template_text",      "TEXT"),
    # Step 15 — 점진적 앱개발
    ("project_type",       "TEXT"),
    ("referenced_context", "TEXT"),
    ("todo_list",          "TEXT"),
    ("current_todo_idx",   "INTEGER DEFAULT 0"),
    ("todo_status",        "TEXT"),
    ("preview_port",       "INTEGER"),
]


def _ensure_v4_columns(conn: sqlite3.Connection) -> None:
    """
    기존 v3 DB에 v4 컬럼을 ALTER TABLE로 추가.
    이미 있는 컬럼은 건너뜀 (멱등성).
    """
    # artifacts 테이블
    existing = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
    for col_name, col_type in _V4_NEW_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE artifacts ADD COLUMN {col_name} {col_type}")

    # projects 테이블 — Step 15에서 project_type 추가
    proj_existing = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
    if "project_type" not in proj_existing:
        conn.execute(
            "ALTER TABLE projects ADD COLUMN project_type TEXT DEFAULT 'doc_generation'"
        )

    conn.commit()


def _connect(db_path: str) -> sqlite3.Connection:
    """
    DB 연결 + 스키마 보장.
    - 신규 DB: CREATE TABLE 실행
    - 기존 v3 DB: ALTER TABLE로 v4 컬럼 추가
    - Step 14-1: llm_calls 테이블 + 인덱스 보장
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_DDL_ARTIFACTS)
    conn.execute(_DDL_PROJECTS)
    conn.execute(_DDL_LLM_CALLS)
    for idx_sql in _INDEXES_LLM_CALLS:
        conn.execute(idx_sql)
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


# ---------------------------------------------------------------------------
# Step 14-1 신규 API — llm_calls 테이블 (비용·토큰 추적)
# ---------------------------------------------------------------------------

def log_llm_call(
    db_path: str,
    project_id: Optional[str],
    run_id: Optional[str],
    phase: Optional[str],
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float = 0.0,
    cached: bool = False,
    duration_ms: int = 0,
    status: str = "success",
    error: Optional[str] = None,
) -> int:
    """
    LLM 호출 1건을 기록. 실패해도 예외 전파 없음 (로그만 실패).

    Args:
      project_id: 소속 프로젝트 (없으면 None)
      run_id:     소속 run (없으면 None)
      phase:      "0.5" / "1" / "3a" / "3b" / "4-structure" / "5" 등
      model:      OpenRouter 모델 ID
      prompt_tokens / completion_tokens: usage에서 파싱한 값
      cost_usd:   calculate_cost 결과
      cached:     프롬프트 캐싱 히트 여부
      duration_ms: 호출 소요 시간 (밀리초)
      status:     "success" | "failed" | "skipped"
      error:      실패 시 에러 메시지 (선택)

    Returns:
      삽입된 row의 id. 실패 시 -1.
    """
    # 방어적 처리
    p_tok = max(0, int(prompt_tokens or 0))
    c_tok = max(0, int(completion_tokens or 0))
    total_tok = p_tok + c_tok
    cost = max(0.0, float(cost_usd or 0.0))
    dur = max(0, int(duration_ms or 0))
    cached_int = 1 if cached else 0

    try:
        conn = _connect(db_path)
        cursor = conn.execute(
            """
            INSERT INTO llm_calls (
                project_id, run_id, phase, model,
                prompt_tokens, completion_tokens, total_tokens,
                cost_usd, cached, duration_ms, status, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, run_id, phase, model,
                p_tok, c_tok, total_tok,
                cost, cached_int, dur, status, error, utc_now_iso(),
            ),
        )
        row_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return row_id if row_id is not None else -1
    except Exception:
        # 로깅 실패는 무시 (프로덕션 흐름 방해 금지)
        return -1


def get_project_total_cost(db_path: str, project_id: str) -> float:
    """
    프로젝트 누적 비용 (USD).

    성공·실패·캐시 관계없이 모든 호출의 cost_usd 합계.
    BudgetGuard가 이 값을 읽어 상한 체크.
    """
    if not project_id:
        return 0.0
    try:
        conn = _connect(db_path)
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) FROM llm_calls WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        conn.close()
        return float(row[0]) if row else 0.0
    except Exception:
        return 0.0


def get_run_llm_calls(
    db_path: str,
    run_id: str,
) -> List[Dict[str, Any]]:
    """
    특정 run의 모든 LLM 호출 내역 (시간순).

    Phase별 소비 분석·디버깅용.
    """
    if not run_id:
        return []
    try:
        conn = _connect(db_path)
        rows = conn.execute(
            "SELECT * FROM llm_calls WHERE run_id = ? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
        conn.close()
        return [_llm_call_row_to_dict(row) for row in rows]
    except Exception:
        return []


def get_recent_llm_calls(
    db_path: str,
    limit: int = 50,
    project_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    최근 LLM 호출 내역 (역시간순).

    Args:
      limit: 반환 최대 개수 (1~1000)
      project_id: 특정 프로젝트만 필터링 (None이면 전체)
    """
    limit = max(1, min(int(limit or 50), 1000))
    try:
        conn = _connect(db_path)
        if project_id:
            rows = conn.execute(
                """
                SELECT * FROM llm_calls
                WHERE project_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM llm_calls ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        conn.close()
        return [_llm_call_row_to_dict(row) for row in rows]
    except Exception:
        return []


def _llm_call_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """llm_calls row → dict. cached INTEGER → bool 복원."""
    result: Dict[str, Any] = {}
    for key in row.keys():
        val = row[key]
        if key == "cached" and val is not None:
            result[key] = bool(val)
        else:
            result[key] = val
    return result
