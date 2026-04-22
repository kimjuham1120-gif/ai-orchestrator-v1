"""
src/web/app.py — v4 웹 UI (Day 122, Step 11, 덮어쓰기)

FastAPI + Jinja2 템플릿 기반 최소 MVP.
  - 7-Phase 워크플로우 UI
  - 폼 + 버튼 + 상태 표시 (실시간 기능 없음, v4.1로 이연)
  - 인증 없음 (단일 사용자 로컬 전용)

라우트:
  GET  /                            — 새 프로젝트 시작 페이지
  POST /projects                    — 새 프로젝트 생성 (Phase 0.5 실행)
  GET  /projects                    — 전체 프로젝트 리스트
  GET  /project/{pid}               — 프로젝트 상태 대시보드
  POST /project/{pid}/phase-1       — Phase 1 실행
  POST /project/{pid}/phase-2       — Phase 2 실행
  POST /project/{pid}/phase-3       — Phase 3 실행
  POST /project/{pid}/phase-4       — Phase 4 실행 (옵션)
  GET  /project/{pid}/phase-5       — 피드백 입력 페이지
  POST /project/{pid}/phase-5/feedback — 피드백 적용
  POST /project/{pid}/phase-5/confirm  — 최종 확정
  GET  /project/{pid}/phase-6       — 트랙 선택 페이지
  POST /project/{pid}/phase-6       — 결정 제출
  GET  /project/{pid}/phase-7       — Phase 7 대시보드
  POST /project/{pid}/phase-7/start — Phase 7 진입
  POST /project/{pid}/phase-7/approval — 승인 결정
  POST /project/{pid}/phase-7/packet   — 패킷 생성
  POST /project/{pid}/phase-7/execution-result — 실행 결과 입력
  POST /project/{pid}/phase-7/verification     — 검증
  POST /project/{pid}/phase-7/finalize         — 최종 요약
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.web.handlers import (
    handle_phase_0_5, handle_phase_1, handle_phase_2,
    handle_phase_3, handle_phase_4,
    handle_phase_5_feedback, handle_phase_5_confirm,
    handle_phase_6,
    handle_phase_7_start, handle_phase_7_approval, handle_phase_7_packet,
    handle_phase_7_execution_result, handle_phase_7_verification,
    handle_phase_7_finalize,
    get_project_status, list_all_projects,
)


# ---------------------------------------------------------------------------
# 앱 구성
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("ORCHESTRATOR_DB_PATH", "orchestrator_v1.db")
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="AI Orchestrator v4", version="4.0.0")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# 루트 — 새 프로젝트
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
            "error": None},
    )


@app.post("/projects")
async def create_project(request: Request, raw_input: str = Form("")):
    result = handle_phase_0_5(raw_input, DB_PATH)
    if not result["ok"]:
        return templates.TemplateResponse(request, "index.html", {
            "error": result.get("error")},
        )
    return RedirectResponse(
        f"/project/{result['project_id']}", status_code=303,
    )


@app.get("/projects", response_class=HTMLResponse)
async def projects_list(request: Request):
    result = list_all_projects(DB_PATH)
    return templates.TemplateResponse(request, "projects_list.html", {
            "projects": result["projects"], "error": result.get("error")},
    )


# ---------------------------------------------------------------------------
# 프로젝트 상태 대시보드
# ---------------------------------------------------------------------------

@app.get("/project/{project_id}", response_class=HTMLResponse)
async def project_status(project_id: str, request: Request):
    status = get_project_status(project_id, DB_PATH)
    if not status["ok"]:
        return templates.TemplateResponse(request, "index.html", {
            "error": status.get("error")},
        )
    return templates.TemplateResponse(request, "project_status.html", {
            "project": status["project"],
            "runs": status["runs"],
            "artifact": status["runs"][0] if status["runs"] else {},
        },
    )


# ---------------------------------------------------------------------------
# Phase 1 — 서브주제 분해
# ---------------------------------------------------------------------------

@app.post("/project/{project_id}/phase-1")
async def phase_1(project_id: str):
    handle_phase_1(project_id, DB_PATH)
    return RedirectResponse(f"/project/{project_id}", status_code=303)


# ---------------------------------------------------------------------------
# Phase 2 — 병렬 리서치 (동기 + 긴 타임아웃)
# ---------------------------------------------------------------------------

@app.post("/project/{project_id}/phase-2")
async def phase_2(project_id: str):
    handle_phase_2(project_id, DB_PATH)
    return RedirectResponse(f"/project/{project_id}", status_code=303)


# ---------------------------------------------------------------------------
# Phase 3 — 2문서 합성
# ---------------------------------------------------------------------------

@app.post("/project/{project_id}/phase-3")
async def phase_3(project_id: str):
    handle_phase_3(project_id, DB_PATH)
    return RedirectResponse(f"/project/{project_id}", status_code=303)


# ---------------------------------------------------------------------------
# Phase 4 — 3감사관 + 통합
# ---------------------------------------------------------------------------

@app.post("/project/{project_id}/phase-4")
async def phase_4(project_id: str):
    handle_phase_4(project_id, DB_PATH)
    return RedirectResponse(f"/project/{project_id}", status_code=303)


# ---------------------------------------------------------------------------
# Phase 5 — 피드백 루프
# ---------------------------------------------------------------------------

@app.get("/project/{project_id}/phase-5", response_class=HTMLResponse)
async def phase_5_page(project_id: str, request: Request):
    status = get_project_status(project_id, DB_PATH)
    if not status["ok"]:
        return RedirectResponse("/", status_code=303)

    artifact = status["runs"][0] if status["runs"] else {}
    return templates.TemplateResponse(request, "phase_5.html", {
            "project": status["project"],
            "target_doc": artifact.get("target_doc"),
            "doc_versions": artifact.get("doc_versions") or [],
        },
    )


@app.post("/project/{project_id}/phase-5/feedback")
async def phase_5_feedback(project_id: str, user_feedback: str = Form(...)):
    handle_phase_5_feedback(project_id, DB_PATH, user_feedback)
    return RedirectResponse(f"/project/{project_id}/phase-5", status_code=303)


@app.post("/project/{project_id}/phase-5/confirm")
async def phase_5_confirm(project_id: str):
    handle_phase_5_confirm(project_id, DB_PATH)
    return RedirectResponse(f"/project/{project_id}/phase-6", status_code=303)


# ---------------------------------------------------------------------------
# Phase 6 — 트랙 선택
# ---------------------------------------------------------------------------

@app.get("/project/{project_id}/phase-6", response_class=HTMLResponse)
async def phase_6_page(project_id: str, request: Request):
    status = get_project_status(project_id, DB_PATH)
    if not status["ok"]:
        return RedirectResponse("/", status_code=303)

    artifact = status["runs"][0] if status["runs"] else {}
    return templates.TemplateResponse(request, "phase_6.html", {
            "project": status["project"],
            "target_doc": artifact.get("target_doc"),
        },
    )


@app.post("/project/{project_id}/phase-6")
async def phase_6_decide(project_id: str, decision: str = Form(...)):
    result = handle_phase_6(project_id, DB_PATH, decision)
    if result["ok"] and result["decision"] == "app_dev":
        return RedirectResponse(f"/project/{project_id}/phase-7", status_code=303)
    return RedirectResponse(f"/project/{project_id}", status_code=303)


# ---------------------------------------------------------------------------
# Phase 7 — 앱개발
# ---------------------------------------------------------------------------

@app.get("/project/{project_id}/phase-7", response_class=HTMLResponse)
async def phase_7_page(project_id: str, request: Request):
    status = get_project_status(project_id, DB_PATH)
    if not status["ok"]:
        return RedirectResponse("/", status_code=303)

    # Phase 7 실행된 artifact 찾기 (phase=phase_7인 가장 최근)
    phase_7_runs = [r for r in status["runs"] if r.get("phase") == "phase_7"]
    phase_7_artifact = phase_7_runs[0] if phase_7_runs else {}

    return templates.TemplateResponse(request, "phase_7.html", {
            "project": status["project"],
            "all_runs": status["runs"],
            "phase_7_artifact": phase_7_artifact,
        },
    )


@app.post("/project/{project_id}/phase-7/start")
async def phase_7_start(project_id: str):
    handle_phase_7_start(project_id, DB_PATH)
    return RedirectResponse(f"/project/{project_id}/phase-7", status_code=303)


@app.post("/project/{project_id}/phase-7/approval")
async def phase_7_approval(
    project_id: str, run_id: str = Form(...), decision: str = Form(...),
):
    handle_phase_7_approval(run_id, DB_PATH, decision)
    return RedirectResponse(f"/project/{project_id}/phase-7", status_code=303)


@app.post("/project/{project_id}/phase-7/packet")
async def phase_7_packet(project_id: str, run_id: str = Form(...)):
    handle_phase_7_packet(run_id, DB_PATH, ".")
    return RedirectResponse(f"/project/{project_id}/phase-7", status_code=303)


@app.post("/project/{project_id}/phase-7/execution-result")
async def phase_7_execution_result(
    project_id: str,
    run_id: str = Form(...),
    changed_files: str = Form(""),
    test_results: str = Form(""),
    run_log: str = Form(""),
):
    files_list = [f.strip() for f in changed_files.split(",") if f.strip()]
    handle_phase_7_execution_result(
        run_id, DB_PATH, files_list, test_results, run_log,
    )
    return RedirectResponse(f"/project/{project_id}/phase-7", status_code=303)


@app.post("/project/{project_id}/phase-7/verification")
async def phase_7_verification(project_id: str, run_id: str = Form(...)):
    handle_phase_7_verification(run_id, DB_PATH)
    return RedirectResponse(f"/project/{project_id}/phase-7", status_code=303)


@app.post("/project/{project_id}/phase-7/finalize")
async def phase_7_finalize(project_id: str, run_id: str = Form(...)):
    handle_phase_7_finalize(run_id, DB_PATH)
    return RedirectResponse(f"/project/{project_id}/phase-7", status_code=303)


# ---------------------------------------------------------------------------
# 헬스체크
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "version": "4.0.0"}
