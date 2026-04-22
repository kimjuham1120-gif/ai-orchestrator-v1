"""
Day 113 — v4 스키마 확장 검증 테스트.

검증 포인트:
1. 신규 DB: artifacts + projects 테이블 모두 생성
2. 기존 v3 DB: v4 컬럼이 ALTER TABLE로 추가
3. 멱등성: 여러 번 _connect() 호출해도 오류 없음
4. 기존 v3 API 하위호환 (save_artifact / load_artifact / update_artifact)
5. 신규 v4 API (save_project / load_project / update_project / list_project_runs)
6. v4 JSON 컬럼 직렬화 (subtopics, parallel_research 등)
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest


# ===========================================================================
# 1. 스키마 생성 검증
# ===========================================================================

class TestSchemaCreation:
    def test_new_db_creates_artifacts_table(self, tmp_path):
        from src.store.artifact_store import _connect
        db = str(tmp_path / "test.db")
        conn = _connect(db)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='artifacts'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_new_db_creates_projects_table(self, tmp_path):
        from src.store.artifact_store import _connect
        db = str(tmp_path / "test.db")
        conn = _connect(db)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_artifacts_has_all_v4_columns(self, tmp_path):
        from src.store.artifact_store import _connect
        db = str(tmp_path / "test.db")
        conn = _connect(db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
        conn.close()

        v4_cols = {
            "project_id", "phase", "feasibility_result", "subtopics",
            "parallel_research", "base_info_doc", "target_doc",
            "cross_audit_v4", "doc_versions", "feedback_history",
            "bridge_decision",
        }
        missing = v4_cols - cols
        assert not missing, f"누락 컬럼: {missing}"

    def test_artifacts_preserves_v3_columns(self, tmp_path):
        from src.store.artifact_store import _connect
        db = str(tmp_path / "test.db")
        conn = _connect(db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
        conn.close()

        v3_required = {
            "run_id", "thread_id", "raw_input", "task_type",
            "research_bundle", "initial_document", "canonical_doc",
            "deliverable_spec", "plan", "builder_output",
            "execution_result", "result_verification", "final_summary",
            "run_status",
        }
        missing = v3_required - cols
        assert not missing, f"v3 컬럼 누락: {missing}"

    def test_projects_schema(self, tmp_path):
        from src.store.artifact_store import _connect
        db = str(tmp_path / "test.db")
        conn = _connect(db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
        conn.close()

        required = {
            "project_id", "title", "raw_input",
            "created_at", "updated_at", "current_phase", "status",
        }
        missing = required - cols
        assert not missing, f"projects 컬럼 누락: {missing}"


# ===========================================================================
# 2. 멱등성 검증
# ===========================================================================

class TestIdempotency:
    def test_multiple_connects_no_error(self, tmp_path):
        """_connect()를 여러 번 호출해도 오류 없음."""
        from src.store.artifact_store import _connect
        db = str(tmp_path / "test.db")
        for _ in range(5):
            conn = _connect(db)
            conn.close()

    def test_existing_v3_db_gets_v4_columns(self, tmp_path):
        """v3 스키마로 먼저 만든 DB에 v4 컬럼이 추가됨."""
        db = str(tmp_path / "v3.db")
        # v3 방식으로 minimal artifacts 테이블 생성
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE artifacts (
                run_id TEXT PRIMARY KEY,
                thread_id TEXT,
                raw_input TEXT,
                task_type TEXT,
                run_status TEXT
            )
        """)
        conn.commit()
        conn.close()

        # v4 _connect() 호출로 컬럼 추가되어야 함
        from src.store.artifact_store import _connect
        conn = _connect(db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
        conn.close()

        # 최소한 v4 신규 컬럼이 들어와야 함
        assert "project_id" in cols
        assert "subtopics" in cols
        assert "cross_audit_v4" in cols


# ===========================================================================
# 3. v3 하위호환 — 기존 API가 그대로 동작
# ===========================================================================

class TestV3Compatibility:
    def test_save_and_load_v3_artifact(self, tmp_path):
        """v3 형태의 artifact dict를 저장·로드."""
        from src.store.artifact_store import save_artifact, load_artifact
        db = str(tmp_path / "test.db")
        artifact = {
            "run_id": "run-v3-001",
            "thread_id": "thr-001",
            "raw_input": "로그인 버그 수정",
            "task_type": "code_fix",
            "run_status": "classified",
        }
        save_artifact(db, artifact)
        loaded = load_artifact(db, run_id="run-v3-001")
        assert loaded is not None
        assert loaded["raw_input"] == "로그인 버그 수정"
        assert loaded["task_type"] == "code_fix"

    def test_update_v3_artifact(self, tmp_path):
        from src.store.artifact_store import save_artifact, update_artifact, load_artifact
        db = str(tmp_path / "test.db")
        save_artifact(db, {"run_id": "run-001", "raw_input": "요청"})
        update_artifact(db, "run-001", {"run_status": "completed"})
        loaded = load_artifact(db, run_id="run-001")
        assert loaded["run_status"] == "completed"

    def test_v3_json_column_roundtrip(self, tmp_path):
        """v3 JSON 컬럼 (research_bundle 등) 정상 직렬화/역직렬화."""
        from src.store.artifact_store import save_artifact, load_artifact
        db = str(tmp_path / "test.db")
        bundle = {"claims": [{"text": "finding A", "source": "docs"}]}
        save_artifact(db, {
            "run_id": "run-001",
            "research_bundle": bundle,
        })
        loaded = load_artifact(db, run_id="run-001")
        assert loaded["research_bundle"] == bundle


# ===========================================================================
# 4. v4 신규 API — projects 테이블
# ===========================================================================

class TestProjectsAPI:
    def test_save_and_load_project(self, tmp_path):
        from src.store.artifact_store import save_project, load_project
        db = str(tmp_path / "test.db")
        proj = {
            "project_id": "proj-001",
            "title": "사업계획서",
            "raw_input": "앱 사업계획서 써줘",
            "created_at": "2026-04-21T00:00:00Z",
            "current_phase": "phase_0_5_gate",
            "status": "in_progress",
        }
        save_project(db, proj)
        loaded = load_project(db, "proj-001")
        assert loaded is not None
        assert loaded["title"] == "사업계획서"
        assert loaded["status"] == "in_progress"

    def test_save_project_requires_project_id(self, tmp_path):
        from src.store.artifact_store import save_project
        db = str(tmp_path / "test.db")
        with pytest.raises(ValueError, match="project_id"):
            save_project(db, {"title": "no id"})

    def test_load_nonexistent_project(self, tmp_path):
        from src.store.artifact_store import load_project
        db = str(tmp_path / "test.db")
        assert load_project(db, "nonexistent") is None

    def test_update_project(self, tmp_path):
        from src.store.artifact_store import save_project, update_project, load_project
        db = str(tmp_path / "test.db")
        save_project(db, {
            "project_id": "proj-001",
            "status": "in_progress",
        })
        update_project(db, "proj-001", {"status": "completed"})
        loaded = load_project(db, "proj-001")
        assert loaded["status"] == "completed"

    def test_update_project_phase(self, tmp_path):
        from src.store.artifact_store import save_project, update_project_phase, load_project
        db = str(tmp_path / "test.db")
        save_project(db, {"project_id": "proj-001"})
        update_project_phase(db, "proj-001", "phase_2_research")
        loaded = load_project(db, "proj-001")
        assert loaded["current_phase"] == "phase_2_research"
        assert loaded["status"] == "in_progress"
        assert loaded["updated_at"] is not None

    def test_list_project_runs_returns_in_order(self, tmp_path):
        """프로젝트 내 여러 run이 rowid 순서로 반환됨."""
        from src.store.artifact_store import save_artifact, save_project, list_project_runs
        db = str(tmp_path / "test.db")
        save_project(db, {"project_id": "proj-001"})
        save_artifact(db, {
            "run_id": "run-001",
            "project_id": "proj-001",
            "phase": "phase_1_decompose",
        })
        save_artifact(db, {
            "run_id": "run-002",
            "project_id": "proj-001",
            "phase": "phase_2_research",
        })
        save_artifact(db, {
            "run_id": "run-999",
            "project_id": "other-proj",
            "phase": "phase_1_decompose",
        })
        runs = list_project_runs(db, "proj-001")
        assert len(runs) == 2
        assert runs[0]["run_id"] == "run-001"
        assert runs[1]["run_id"] == "run-002"


# ===========================================================================
# 5. v4 JSON 컬럼 직렬화
# ===========================================================================

class TestV4JsonColumns:
    def test_subtopics_roundtrip(self, tmp_path):
        from src.store.artifact_store import save_artifact, load_artifact
        db = str(tmp_path / "test.db")
        subtopics = ["작성 방법론", "시장 규모", "경쟁사 분석"]
        save_artifact(db, {
            "run_id": "run-001",
            "subtopics": subtopics,
        })
        loaded = load_artifact(db, run_id="run-001")
        assert loaded["subtopics"] == subtopics

    def test_parallel_research_roundtrip(self, tmp_path):
        from src.store.artifact_store import save_artifact, load_artifact
        db = str(tmp_path / "test.db")
        research = {
            "작성 방법론": {
                "gemini": {"claims": [{"text": "A", "source": "docs"}]},
                "gpt": {"status": "failed", "error": "timeout"},
            },
        }
        save_artifact(db, {
            "run_id": "run-001",
            "parallel_research": research,
        })
        loaded = load_artifact(db, run_id="run-001")
        assert loaded["parallel_research"] == research

    def test_cross_audit_v4_roundtrip(self, tmp_path):
        from src.store.artifact_store import save_artifact, load_artifact
        db = str(tmp_path / "test.db")
        audit = {
            "round": 1,
            "audits": {
                "structure": {"role": "구조 감사관", "feedback": "..."},
                "balance":   {"role": "균형 감사관", "feedback": "..."},
                "fact":      {"role": "사실 감사관", "feedback": "..."},
            },
        }
        save_artifact(db, {
            "run_id": "run-001",
            "cross_audit_v4": audit,
        })
        loaded = load_artifact(db, run_id="run-001")
        assert loaded["cross_audit_v4"] == audit

    def test_doc_versions_roundtrip(self, tmp_path):
        from src.store.artifact_store import save_artifact, load_artifact
        db = str(tmp_path / "test.db")
        versions = [
            {"version": 1, "document": "초안", "feedback_applied": None},
            {"version": 2, "document": "개선본", "feedback_applied": "재무 강화"},
        ]
        save_artifact(db, {
            "run_id": "run-001",
            "doc_versions": versions,
        })
        loaded = load_artifact(db, run_id="run-001")
        assert loaded["doc_versions"] == versions

    def test_feasibility_result_roundtrip(self, tmp_path):
        from src.store.artifact_store import save_artifact, load_artifact
        db = str(tmp_path / "test.db")
        result = {
            "verdict": "possible",
            "reason": "문서 산출물로 처리 가능",
            "suggested_clarification": None,
        }
        save_artifact(db, {
            "run_id": "run-001",
            "feasibility_result": result,
        })
        loaded = load_artifact(db, run_id="run-001")
        assert loaded["feasibility_result"] == result


# ===========================================================================
# 7. 하위호환 헬퍼 함수 (v1부터 있던 것들)
# ===========================================================================

class TestHelperFunctions:
    def test_utc_now_iso_returns_iso_string(self):
        """utc_now_iso()는 canonical_freeze 등에서 import하는 함수 — 반드시 존재."""
        from src.store.artifact_store import utc_now_iso
        result = utc_now_iso()
        assert isinstance(result, str)
        assert "T" in result  # ISO 8601 포맷 확인
        assert "+00:00" in result or result.endswith("Z")

    def test_utc_now_iso_is_timezone_aware(self):
        """UTC 타임존 명시 확인."""
        from src.store.artifact_store import utc_now_iso
        from datetime import datetime
        result = utc_now_iso()
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo is not None


# ===========================================================================
# 6. 마이그레이션 스크립트 단위 테스트
# ===========================================================================

class TestMigrationScript:
    def test_migrate_fresh_db(self, tmp_path):
        """새 DB도 마이그레이션 실행 가능 (파일 없으면 스킵)."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from migrate_to_v4 import migrate

        db = str(tmp_path / "nonexistent.db")
        result = migrate(db, dry_run=False)
        # 파일 없으면 빈 결과
        assert result["artifacts_existed"] is False

    def test_migrate_v3_db_adds_v4_columns(self, tmp_path):
        """v3 DB에 마이그레이션 실행 → v4 컬럼 추가."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from migrate_to_v4 import migrate

        db = str(tmp_path / "v3.db")
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE artifacts (
                run_id TEXT PRIMARY KEY,
                raw_input TEXT
            )
        """)
        conn.commit()
        conn.close()

        result = migrate(db, dry_run=False)
        assert result["artifacts_existed"] is True
        assert result["projects_created"] is True
        assert "project_id" in result["columns_added"]
        assert "subtopics" in result["columns_added"]

    def test_migrate_idempotent(self, tmp_path):
        """같은 DB에 두 번 실행 — 두 번째는 모두 skipped."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from migrate_to_v4 import migrate

        db = str(tmp_path / "v3.db")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE artifacts (run_id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        result1 = migrate(db, dry_run=False)
        result2 = migrate(db, dry_run=False)

        assert len(result1["columns_added"]) > 0
        assert len(result2["columns_added"]) == 0
        assert len(result2["columns_skipped"]) == len(result1["columns_added"])

    def test_dry_run_does_not_modify(self, tmp_path):
        """--dry-run 모드는 실제 변경 안 함."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from migrate_to_v4 import migrate

        db = str(tmp_path / "v3.db")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE artifacts (run_id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        migrate(db, dry_run=True)

        # dry-run 후 실제 DB에는 변경 없음
        conn = sqlite3.connect(db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()}
        has_projects = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
        ).fetchone()
        conn.close()

        assert "project_id" not in cols  # 추가 안 됨
        assert has_projects is None  # projects 테이블 생성 안 됨
