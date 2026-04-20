# 범위 문서 — ai-orchestrator-v2 최종 (Day 73~80 확정)

---

## Day별 완료 상태

| Day | 내용 | 상태 |
|-----|------|------|
| Day 28~40 | v1 baseline → 운영 고정 (197 passed) | ✅ |
| Day 41~48 | Perplexity real 연결 | ✅ |
| Day 49~56 | GPT 심층리서치 포함 / Tavily 제외 | ✅ |
| Day 57~64 | OpenRouter 유료 모델 전환 준비 | ✅ |
| Day 65~72 | Gemini Deep Research + Cursor 자동 실행 | ✅ |
| Day 73~80 | v2 마감 정리 / 문서 고정 / 294 passed | ✅ |

---

## v2 확정 구조

### Research 계층

```
핵심 (심층리서치):
  Gemini Deep Research  GEMINI_API_KEY   → Interactions API, deep-research-pro-preview-12-2025
  GPT Deep Research     OPENAI_API_KEY   → Responses API, o4-mini-deep-research

support:
  Perplexity            PERPLEXITY_API_KEY → 웹 보강
  Gemini grounding      GEMINI_API_KEY     → 빠른 googleSearch

fallback:
  YouTube stub          (key 없음)         → real 전원 비활성 시만
```

### 실행 계층

```
Planner  : OpenRouter → OPENROUTER_PLANNER_MODEL (gpt-5.4)
Builder  : OpenRouter → OPENROUTER_BUILDER_MODEL (claude-sonnet-4.6)
Doc      : OpenRouter → OPENROUTER_DOC_MODEL (gpt-5.4-mini)
Reviewer : OpenRouter → OPENROUTER_REVIEWER_MODEL (gpt-5.4-mini)
```

### Cursor 실행

```
자동: CURSOR_AUTO_MODE=true → Background Agent API → polling
수동: CURSOR_AUTO_MODE=false (기본) → packet 파일 수동 실행
실패: 자동 실패 → 수동 fallback 자동 전환
```

---

## v2 완료 기준

| 기준 | 상태 |
|------|------|
| 294 passed (timeout 없음) | ✅ |
| GPT Deep Research real 호출 확인 | ✅ |
| Gemini Deep Research (Interactions API) 구현 | ✅ |
| Cursor 자동/수동 실행 계층 | ✅ |
| OpenRouter 역할별 모델 분리 | ✅ |
| 실패 복구 (slice_issue / doc_issue) | ✅ |
| silent fallback 없음 | ✅ |
| artifact_store 스키마 변경 없음 | ✅ |

---

## 비범위 (v2에서 하지 않음)

| 항목 | 이유 |
|------|------|
| Cursor API endpoint 실제 검증 | API 미확정 |
| FastAPI 웹 UI | v3 |
| 멀티 slice 병렬 실행 | v3 |
| EvidenceBundle scoring | v3 |
| Gemini Deep Research smoke test | polling 시간 소요 |

---

## v3 백로그

| 항목 | 우선순위 |
|------|----------|
| Cursor Background Agent API 실제 검증 | 높음 |
| FastAPI 웹 UI + 상태 대시보드 | 중간 |
| 멀티 slice 병렬 실행 | 낮음 |
| EvidenceBundle 품질 scoring | 낮음 |
| Gemini Deep Research smoke test | 높음 (키 준비 후) |

---

## 고정 키 구조

```env
# 필수
OPENROUTER_API_KEY
GEMINI_API_KEY

# 역할별 모델
OPENROUTER_PLANNER_MODEL
OPENROUTER_BUILDER_MODEL
OPENROUTER_DOC_MODEL
OPENROUTER_REVIEWER_MODEL
OPENROUTER_BASE_URL
OPENROUTER_PLANNER_REASONING_EFFORT
OPENROUTER_BUILDER_VERBOSITY

# GPT Deep Research
OPENAI_API_KEY
GPT_RESEARCH_MODEL
GPT_RESEARCH_TIMEOUT
GPT_RESEARCH_MAX_TOKENS

# Gemini Deep Research
GEMINI_DEEP_RESEARCH_AGENT
GEMINI_DEEP_RESEARCH_TIMEOUT
GEMINI_DEEP_RESEARCH_POLL_INTERVAL
GEMINI_DEEP_RESEARCH_MAX_CLAIMS

# support
PERPLEXITY_API_KEY

# Cursor
CURSOR_AUTO_MODE
CURSOR_API_KEY
CURSOR_REPO_PATH
CURSOR_EXECUTION_TIMEOUT
CURSOR_POLL_INTERVAL
```
