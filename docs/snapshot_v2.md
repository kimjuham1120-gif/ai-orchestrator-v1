# 최종 스냅샷 — ai-orchestrator-v2 (Day 73~80)

---

## 테스트 상태

```
294 passed, 1 warning (Python 3.14 / pytest 9.0.3)
경고: google-genai SDK DeprecationWarning — 무해
timeout: --timeout=30 권장
```

---

## 파일 구조

```
ai-orchestrator-v1/
├── src/
│   ├── approval/approval_service.py
│   ├── builder/builder_config.py         ← v2 수정 (openrouter/auto, _OPENROUTER_URL)
│   ├── builder/builder_service.py
│   ├── builder/builder_schema.py
│   ├── classifier/classifier.py
│   ├── cli.py                             ← v2 수정 (auto/manual 분기)
│   ├── cursor/
│   │   ├── __init__.py
│   │   ├── cursor_executor.py             ← v2 신규
│   │   └── cursor_result_adapter.py       ← v2 신규
│   ├── document/
│   │   ├── canonical_freeze.py
│   │   ├── cross_audit.py
│   │   ├── deliverable_spec.py
│   │   ├── document_config.py             ← v2 신규
│   │   └── initial_generator.py
│   ├── finalize/finalize_service.py
│   ├── graph_flow.py
│   ├── orchestrator.py
│   ├── packet/packet_builder.py
│   ├── planner/
│   │   ├── planner_config.py              ← v2 수정
│   │   ├── planner_schema.py
│   │   └── planner_service.py
│   ├── planning/backward_planner.py
│   ├── planning/slice_queue.py
│   ├── research/
│   │   ├── base.py
│   │   ├── brave_adapter.py
│   │   ├── evidence_bundle.py
│   │   ├── gemini_adapter.py              ← grounding (support)
│   │   ├── gemini_deep_research_adapter.py ← v2 신규 (Interactions API)
│   │   ├── google_adapter.py              ← disabled
│   │   ├── gpt_research_adapter.py        ← v2 신규 (Responses API)
│   │   ├── perplexity_adapter.py          ← v2 real 연결
│   │   ├── router.py                      ← v2 수정 (DEEP/SUPPORT/FALLBACK)
│   │   ├── tavily_adapter.py              ← disabled
│   │   └── youtube_adapter.py             ← fallback stub
│   ├── reviewer/
│   │   ├── llm_reviewer.py
│   │   ├── review_gate.py
│   │   ├── reviewer_config.py             ← v2 신규
│   │   └── rule_checker.py
│   ├── store/artifact_store.py
│   ├── utils/id_generator.py
│   └── verification/
│       ├── result_verifier.py
│       └── spec_alignment.py
├── tests/                                 ← 294 tests
├── docs/
│   ├── cursor_manual_execution.md         ← v2 수정
│   ├── failure_recovery.md                ← v2 수정
│   ├── ops_checklist.md
│   ├── resume_flow.md
│   ├── runbook.md                         ← v2 수정
│   ├── scope.md                           ← v2 최종
│   ├── setup.md                           ← v2 수정
│   ├── snapshot_v2.md                     ← 이 파일
│   └── success_cases.md
├── .env
├── .env.example                           ← v2 수정
├── orchestrator_v1.db
├── pyproject.toml
└── README.md                              ← v2 수정
```

---

## Research 어댑터 우선순위

| 순위 | 어댑터 | 키 | 분류 |
|------|--------|----|------|
| 1 | GeminiDeepResearchAdapter | `GEMINI_API_KEY` | `_DEEP_RESEARCH_CLASSES` |
| 2 | GPTResearchAdapter | `OPENAI_API_KEY` | `_DEEP_RESEARCH_CLASSES` |
| 3 | PerplexityAdapter | `PERPLEXITY_API_KEY` | `_SUPPORT_ADAPTER_CLASSES` |
| 4 | GeminiResearchAdapter | `GEMINI_API_KEY` | `_SUPPORT_ADAPTER_CLASSES` |
| 5 | YouTubeTranscriptAdapter | 없음 | `_FALLBACK_ADAPTER_CLASSES` |

---

## 대표 run_id

| 사례 | run_id | 결과 |
|------|--------|------|
| Day 36 완주 | run-207f32b7 | completed |
| Day 48 Perplexity smoke | run-b1d316cb | smoke test |
| Day 65 GPT smoke | run-8341579f | smoke test (11 claims) |

---

## v2 종료 선언

**완료:**
- Research 계층: GPT + Gemini Deep Research 핵심 축 완성
- Cursor 자동 실행 계층 구현 (자동/수동 fallback)
- OpenRouter 역할별 모델 분리
- 실패 복구 (slice_issue / doc_issue) 검증
- 294 passed, silent fallback 없음

**선택 과제 (v3):**
- Cursor API endpoint 실제 검증
- Gemini Deep Research smoke test
- FastAPI 웹 UI
- 멀티 slice 병렬 실행
