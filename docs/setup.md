# Setup Guide — ai-orchestrator-v2 (Day 81~88 반영)

## 요구 사항

| 항목 | 버전 |
|------|------|
| Python | 3.11 이상 |
| pip | 23 이상 |

## 1. 설치

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pip install fastapi uvicorn httpx  # 웹 UI 추가 의존성
```

## 2. 환경변수 (.env)

```env
# OpenRouter (필수)
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_PLANNER_MODEL=openai/gpt-5.4
OPENROUTER_BUILDER_MODEL=anthropic/claude-sonnet-4.6
OPENROUTER_DOC_MODEL=openai/gpt-5.4-mini
OPENROUTER_REVIEWER_MODEL=openai/gpt-5.4-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_PLANNER_REASONING_EFFORT=high
OPENROUTER_BUILDER_VERBOSITY=high

# Gemini Deep Research (필수)
GEMINI_API_KEY=AIza...
GEMINI_DEEP_RESEARCH_AGENT=deep-research-pro-preview-12-2025
GEMINI_DEEP_RESEARCH_TIMEOUT=600.0
GEMINI_DEEP_RESEARCH_POLL_INTERVAL=10.0

# GPT Deep Research
OPENAI_API_KEY=sk-...
GPT_RESEARCH_MODEL=openai/o4-mini-deep-research
GPT_RESEARCH_TIMEOUT=120.0
GPT_RESEARCH_MAX_TOKENS=2000

# Support
PERPLEXITY_API_KEY=pplx-...

# Cursor 자동 실행 (선택)
CURSOR_AUTO_MODE=false
CURSOR_API_KEY=cursor-...
CURSOR_REPO_PATH=.

# 웹 UI DB 경로 (기본: orchestrator_v1.db)
ORCHESTRATOR_DB=orchestrator_v1.db
```

## 3. 실행

### CLI 모드 (기존)
```bash
python -m src.cli
```

### 웹 UI 모드 (신규)
```bash
uvicorn src.web.app:app --reload --port 8000
# 브라우저: http://localhost:8000
```

CLI와 웹 UI는 동일한 DB를 바라보므로 병행 운영 가능.

## 4. 테스트

```bash
pytest -v --timeout=30
# 목표: ~330 passed
```

## 5. 웹 UI 기능

| 페이지 | URL | 기능 |
|--------|-----|------|
| 목록 | `http://localhost:8000/` | 전체 run 목록, 상태 표시 |
| 상세 | `http://localhost:8000/runs/{run_id}` | run 상세, approve/reject 버튼 |

| API | Method | URL | 기능 |
|-----|--------|-----|------|
| Health | GET | `/api/health` | 서버 상태 |
| 목록 | GET | `/api/runs` | runs JSON |
| 상세 | GET | `/api/runs/{run_id}` | run 상세 JSON |
| Approve | POST | `/api/runs/{run_id}/approve` | 승인 |
| Reject | POST | `/api/runs/{run_id}/reject` | 거절 |
