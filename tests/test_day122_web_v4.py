"""
Day 122 — v4 웹 UI 통합 테스트.

검증 포인트:
1. 라우트 구성 (모든 엔드포인트 존재)
2. 루트 페이지 렌더링
3. 프로젝트 생성 (Phase 0.5 경로)
4. 프로젝트 목록
5. 프로젝트 상태 대시보드
6. Phase 5/6/7 페이지 렌더링
7. 헬스체크
8. handlers 함수 존재 확인
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# 라우트/앱 로딩
# ---------------------------------------------------------------------------

class TestAppLoading:
    def test_app_imports_without_error(self):
        from src.web.app import app
        assert app is not None
        assert app.title == "AI Orchestrator v4"

    def test_expected_routes_exist(self):
        from src.web.app import app
        routes = {r.path for r in app.routes if hasattr(r, "path")}
        expected = {
            "/",
            "/projects",
            "/project/{project_id}",
            "/project/{project_id}/phase-1",
            "/project/{project_id}/phase-2",
            "/project/{project_id}/phase-3",
            "/project/{project_id}/phase-4",
            "/project/{project_id}/phase-5",
            "/project/{project_id}/phase-5/feedback",
            "/project/{project_id}/phase-5/confirm",
            "/project/{project_id}/phase-6",
            "/project/{project_id}/phase-7",
            "/project/{project_id}/phase-7/start",
            "/project/{project_id}/phase-7/approval",
            "/project/{project_id}/phase-7/packet",
            "/project/{project_id}/phase-7/execution-result",
            "/project/{project_id}/phase-7/verification",
            "/project/{project_id}/phase-7/finalize",
            "/health",
        }
        missing = expected - routes
        assert not missing, f"누락된 라우트: {missing}"


# ---------------------------------------------------------------------------
# 기본 페이지 렌더링
# ---------------------------------------------------------------------------

class TestPageRendering:
    def test_index_page_renders(self):
        from fastapi.testclient import TestClient
        from src.web.app import app
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert "새 프로젝트 시작" in response.text

    def test_projects_list_page_renders(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORCHESTRATOR_DB_PATH", str(tmp_path / "test.db"))
        # app은 이미 import됨이라 DB_PATH 재설정 위해 리로드
        import importlib
        from src.web import app as web_app
        importlib.reload(web_app)

        from fastapi.testclient import TestClient
        client = TestClient(web_app.app)
        response = client.get("/projects")
        assert response.status_code == 200
        assert "프로젝트 목록" in response.text

    def test_health_endpoint(self):
        from fastapi.testclient import TestClient
        from src.web.app import app
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "4.0.0"


# ---------------------------------------------------------------------------
# handlers 함수 존재 확인
# ---------------------------------------------------------------------------

class TestHandlersAPI:
    def test_all_handler_functions_exist(self):
        from src.web import handlers
        expected = [
            "handle_phase_0_5",
            "handle_phase_1",
            "handle_phase_2",
            "handle_phase_3",
            "handle_phase_4",
            "handle_phase_5_feedback",
            "handle_phase_5_confirm",
            "handle_phase_6",
            "handle_phase_7_start",
            "handle_phase_7_approval",
            "handle_phase_7_packet",
            "handle_phase_7_execution_result",
            "handle_phase_7_verification",
            "handle_phase_7_finalize",
            "get_project_status",
            "list_all_projects",
        ]
        for fn_name in expected:
            assert hasattr(handlers, fn_name), f"누락 함수: {fn_name}"
            assert callable(getattr(handlers, fn_name))


# ---------------------------------------------------------------------------
# handle_phase_0_5 (DB 상호작용)
# ---------------------------------------------------------------------------

class TestPhase0_5Handler:
    def test_empty_input_returns_error(self, tmp_path):
        from src.web.handlers import handle_phase_0_5
        result = handle_phase_0_5("", str(tmp_path / "x.db"))
        assert result["ok"] is False
        assert "error" in result

    def test_whitespace_only_returns_error(self, tmp_path):
        from src.web.handlers import handle_phase_0_5
        result = handle_phase_0_5("   \n  ", str(tmp_path / "x.db"))
        assert result["ok"] is False

    def test_possible_request_creates_project(self, tmp_path):
        """규칙 기반으로 possible 판정 → 프로젝트 생성됨."""
        from src.web.handlers import handle_phase_0_5
        from src.store.artifact_store import load_project

        db = str(tmp_path / "x.db")
        result = handle_phase_0_5("사업계획서 써줘", db)

        assert result["ok"] is True
        assert result["verdict"] == "possible"
        assert result["project_id"].startswith("proj-")

        # DB에도 저장됨
        project = load_project(db, result["project_id"])
        assert project is not None
        assert project["raw_input"] == "사업계획서 써줘"

    def test_out_of_scope_creates_blocked_project(self, tmp_path):
        from src.web.handlers import handle_phase_0_5
        from src.store.artifact_store import load_project

        db = str(tmp_path / "x.db")
        result = handle_phase_0_5("오늘 날씨 알려줘", db)

        assert result["ok"] is True  # 판정 자체는 성공
        assert result["verdict"] == "out_of_scope"

        project = load_project(db, result["project_id"])
        assert project["status"] == "blocked"


# ---------------------------------------------------------------------------
# 프로젝트 상태 조회
# ---------------------------------------------------------------------------

class TestGetProjectStatus:
    def test_nonexistent_returns_error(self, tmp_path):
        from src.web.handlers import get_project_status
        result = get_project_status("nonexistent", str(tmp_path / "x.db"))
        assert result["ok"] is False
        assert "error" in result

    def test_existing_project_returns_all_runs(self, tmp_path):
        from src.web.handlers import handle_phase_0_5, get_project_status
        db = str(tmp_path / "x.db")

        # 프로젝트 생성
        create = handle_phase_0_5("사업계획서 써줘", db)
        assert create["ok"]

        # 상태 조회
        status = get_project_status(create["project_id"], db)
        assert status["ok"] is True
        assert status["project"]["project_id"] == create["project_id"]
        assert isinstance(status["runs"], list)


# ---------------------------------------------------------------------------
# list_all_projects
# ---------------------------------------------------------------------------

class TestListAllProjects:
    def test_empty_db_returns_empty_list(self, tmp_path):
        from src.web.handlers import list_all_projects
        result = list_all_projects(str(tmp_path / "empty.db"))
        assert result["ok"] is True
        assert result["projects"] == []

    def test_multiple_projects_listed(self, tmp_path):
        from src.web.handlers import handle_phase_0_5, list_all_projects
        db = str(tmp_path / "x.db")

        for i in range(3):
            handle_phase_0_5(f"요청 {i} 사업계획서 써줘", db)

        result = list_all_projects(db)
        assert result["ok"] is True
        assert len(result["projects"]) == 3


# ---------------------------------------------------------------------------
# POST /projects 통합
# ---------------------------------------------------------------------------

class TestCreateProjectEndpoint:
    def test_empty_input_redirects_with_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORCHESTRATOR_DB_PATH", str(tmp_path / "x.db"))
        import importlib
        from src.web import app as web_app
        importlib.reload(web_app)

        from fastapi.testclient import TestClient
        client = TestClient(web_app.app)

        response = client.post(
            "/projects",
            data={"raw_input": ""},
            follow_redirects=False,
        )
        # 에러 시 인덱스로 다시 렌더 (200) 또는 처리 방식에 따라 다름
        assert response.status_code in (200, 303)

    def test_valid_input_redirects_to_project(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORCHESTRATOR_DB_PATH", str(tmp_path / "x.db"))
        import importlib
        from src.web import app as web_app
        importlib.reload(web_app)

        from fastapi.testclient import TestClient
        client = TestClient(web_app.app)

        response = client.post(
            "/projects",
            data={"raw_input": "사업계획서 써줘"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/project/proj-")


# ---------------------------------------------------------------------------
# 템플릿 파일 존재
# ---------------------------------------------------------------------------

class TestTemplateFiles:
    def test_required_templates_exist(self):
        from src.web.app import TEMPLATES_DIR
        required = [
            "base.html",
            "index.html",
            "project_status.html",
            "phase_5.html",
            "phase_6.html",
            "phase_7.html",
            "projects_list.html",
        ]
        for name in required:
            assert (TEMPLATES_DIR / name).exists(), f"누락 템플릿: {name}"

    def test_static_css_exists(self):
        from src.web.app import STATIC_DIR
        assert (STATIC_DIR / "style.css").exists()
