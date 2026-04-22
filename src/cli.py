"""
v4 CLI — 웹 UI 진입점 안내.

v4는 FastAPI 웹 UI를 메인 인터페이스로 사용합니다.
  uvicorn src.web.app:app --reload
  http://localhost:8000

v3 CLI(run_orchestration, resume_from_doc 등)는 Phase 0.5~7로 대체됨.
"""
from __future__ import annotations


def main() -> None:
    print()
    print("=" * 50)
    print("  AI Orchestrator v4")
    print("=" * 50)
    print()
    print("웹 UI로 접속하세요:")
    print()
    print("  uvicorn src.web.app:app --reload")
    print("  → http://localhost:8000")
    print()
    print("또는 직접 Phase API 호출:")
    print("  from src.phases.phase_0_5_gate import check_feasibility")
    print("  from src.phases.phase_7_app_dev import run_phase_7_from_spec")
    print()


if __name__ == "__main__":
    main()
