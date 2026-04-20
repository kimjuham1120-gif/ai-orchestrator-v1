# ai-orchestrator-v2

문서고정 중심 상위 계층 + 역산 실행 구조의 AI 오케스트레이션 엔진.
Day 73~80 기준 v2 마감 완료.

## 빠른 시작

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -e ".[dev]"
cp .env.example .env          # API 키 입력 후 저장
python -m src.cli
```

## 실행 흐름

```
사용자 입력
  → classify (5분류: code_fix / feature / research / review / unsupported)
  → research
      핵심: Gemini Deep Research (Interactions API)
            GPT Deep Research    (Responses API + web_search_preview)
      support: Perplexity / Gemini grounding
      fallback: YouTube stub (real 전원 비활성 시)
  → initial_doc → cross_audit → canonical_freeze
  → deliverable_spec → backward_plan → slice_queue
  → planner → builder → 3-layer review → approval
  → [승인]
      자동: Cursor Background Agent API 호출 → polling → execution_result 자동 수집
      수동: packet 파일 → Cursor 붙여넣기 → 결과 수동 입력
  → result_verifier → spec_alignment
  → finalize
```

## API 키 구성

| 키 | 용도 | 필수 여부 |
|----|------|-----------|
| `OPENROUTER_API_KEY` | planner / builder / doc / reviewer | 없으면 stub |
| `GEMINI_API_KEY` | Gemini Deep Research + grounding | 없으면 YouTube fallback |
| `OPENAI_API_KEY` | GPT Deep Research | 없으면 비활성 |
| `PERPLEXITY_API_KEY` | 웹 보강 support | 없으면 비활성 |
| `CURSOR_API_KEY` | Cursor 자동 실행 | 없으면 수동 모드 |

## 모델 구성 (.env)

```env
OPENROUTER_PLANNER_MODEL=openai/gpt-5.4
OPENROUTER_BUILDER_MODEL=anthropic/claude-sonnet-4.6
OPENROUTER_DOC_MODEL=openai/gpt-5.4-mini
OPENROUTER_REVIEWER_MODEL=openai/gpt-5.4-mini
GPT_RESEARCH_MODEL=openai/o4-mini-deep-research
GEMINI_DEEP_RESEARCH_AGENT=deep-research-pro-preview-12-2025
```

## Cursor 자동 실행

```env
CURSOR_AUTO_MODE=true          # 자동 모드 활성화
CURSOR_API_KEY=cursor-...
CURSOR_REPO_PATH=C:\...\ai-orchestrator-v1
```

자동 실패 시 수동 입력으로 자동 전환.

## 테스트

```bash
pytest -v --timeout=30   # 294 passed
```

## 문서

| 문서 | 내용 |
|------|------|
| `docs/setup.md` | 설치 및 환경변수 전체 목록 |
| `docs/runbook.md` | 운영 절차 및 상태표 |
| `docs/failure_recovery.md` | 실패 시나리오별 복구 |
| `docs/scope.md` | v2 범위 / 비범위 / v3 백로그 |
| `docs/snapshot_v2.md` | v2 최종 스냅샷 |

## v3 백로그

- Cursor Background Agent API 실제 검증 (endpoint 확정 후)
- FastAPI 웹 UI / 상태 대시보드
- 멀티 slice 병렬 실행
- EvidenceBundle 품질 scoring
- OpenRouter 유료 모델 최적화
