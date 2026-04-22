"""
v3 → v4 DB 마이그레이션 스크립트.

멱등성 보장: 여러 번 실행해도 안전.
기존 데이터 전부 보존.

사용법:
  python scripts/migrate_to_v4.py
  python scripts/migrate_to_v4.py --db-path orchestrator_v1.db
  python scripts/migrate_to_v4.py --dry-run         # 변경 없이 상태만 확인
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


V4_NEW_COLUMNS = [
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

PROJECTS_DDL = """
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


def check_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_existing_columns(conn: sqlite3.Connection, table_name: str) -> set:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def migrate(db_path: str, dry_run: bool = False) -> dict:
    """
    마이그레이션 실행.
    반환: {
        "artifacts_existed": bool,
        "projects_created": bool,
        "columns_added": list[str],
        "columns_skipped": list[str],
    }
    """
    result = {
        "artifacts_existed": False,
        "projects_created": False,
        "columns_added": [],
        "columns_skipped": [],
    }

    if not Path(db_path).exists():
        print(f"[INFO] DB 파일 없음: {db_path}")
        print(f"[INFO] 새 DB로 취급, artifact_store._connect()가 CREATE 처리함.")
        return result

    conn = sqlite3.connect(db_path)

    # 1. artifacts 테이블 확인
    result["artifacts_existed"] = check_table_exists(conn, "artifacts")
    if result["artifacts_existed"]:
        existing_cols = get_existing_columns(conn, "artifacts")
        print(f"[INFO] artifacts 테이블 발견 (기존 컬럼 {len(existing_cols)}개)")

        # v4 컬럼 추가
        for col_name, col_type in V4_NEW_COLUMNS:
            if col_name in existing_cols:
                result["columns_skipped"].append(col_name)
            else:
                if dry_run:
                    print(f"[DRY-RUN] ALTER TABLE artifacts ADD COLUMN {col_name} {col_type}")
                else:
                    conn.execute(
                        f"ALTER TABLE artifacts ADD COLUMN {col_name} {col_type}"
                    )
                    print(f"[ADDED] artifacts.{col_name} ({col_type})")
                result["columns_added"].append(col_name)
    else:
        print("[INFO] artifacts 테이블 없음 (첫 실행)")

    # 2. projects 테이블 생성
    if check_table_exists(conn, "projects"):
        print("[INFO] projects 테이블 이미 존재")
        result["projects_created"] = False
    else:
        if dry_run:
            print("[DRY-RUN] CREATE TABLE projects")
        else:
            conn.execute(PROJECTS_DDL)
            print("[CREATED] projects 테이블")
        result["projects_created"] = True

    if not dry_run:
        conn.commit()
    conn.close()

    return result


def print_summary(result: dict, db_path: str, dry_run: bool) -> None:
    print()
    print("=" * 50)
    print(f"마이그레이션 요약 ({'DRY-RUN' if dry_run else 'APPLIED'})")
    print("=" * 50)
    print(f"DB: {db_path}")
    print(f"artifacts 테이블 기존 존재: {result['artifacts_existed']}")
    print(f"projects 테이블 생성: {result['projects_created']}")
    print(f"추가된 v4 컬럼 ({len(result['columns_added'])}개):")
    for c in result["columns_added"]:
        print(f"  + {c}")
    if result["columns_skipped"]:
        print(f"이미 있어 건너뛴 컬럼 ({len(result['columns_skipped'])}개):")
        for c in result["columns_skipped"]:
            print(f"  = {c}")
    print("=" * 50)

    if dry_run:
        print()
        print("실제 적용하려면 --dry-run 옵션 없이 다시 실행하세요.")


def main() -> int:
    parser = argparse.ArgumentParser(description="v3 → v4 DB 마이그레이션")
    parser.add_argument(
        "--db-path",
        default="orchestrator_v1.db",
        help="DB 파일 경로 (기본: orchestrator_v1.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 변경 없이 예정된 작업만 출력",
    )
    args = parser.parse_args()

    print(f"[START] v3 → v4 마이그레이션")
    print(f"[DB] {args.db_path}")
    print(f"[MODE] {'dry-run' if args.dry_run else 'apply'}")
    print()

    try:
        result = migrate(args.db_path, dry_run=args.dry_run)
        print_summary(result, args.db_path, args.dry_run)
        return 0
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
