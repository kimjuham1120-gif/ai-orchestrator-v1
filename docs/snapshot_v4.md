# snapshot_v4.md — v3 → v4 전환 스냅샷 (Day 113 진입)

이 문서는 v3 baseline의 **최종 상태**와 v4 진입 직전 **체크포인트**를 고정합니다.
v4 구현 중 회귀 테스트와 롤백 기준점으로 사용합니다.

---

## 1. v3 최종 상태 (Day 112 종료 시점)

### 테스트 결과
```
411 passed
- 172 (v1 baseline, Day 40)
- 19  (v2 research 계층, Day 48)
- 220 (v3 웹 UI + 2-track, Day 72~112)
```

### 파일 구조 (v3 기준)
```
src/
├── approval/approval_service.py
├── builder/
│   ├── builder_config.py
│   ├── builder_schema.py
│   └── builder_service.py
├── chat/
│   ├── info_retrieval_service.py       ← v4에서 삭제 예정
│   └── research_document_service.py    ← v4에서 삭제 예정
├── classifier/classifier.py
├── cli.py
├── document/
│   ├── canonical_freeze.py
│   ├── cross_audit.py                  ← v4 Phase 4로 교체
│   ├── deliverable_spec.py
│   └── initial_generator.py
├── finalize/finalize_service.py
├── graph_flow.py                       ← v4에서 Phase별 서브그래프로 재설계
├── interpreter/
│   ├── flow_router.py                  ← v4에서 삭제 (Phase 6가 대체)
│   ├── lane_selector.py                ← v4에서 삭제 (Phase 0.5 + Phase 6이 대체)
│   └── request_interpreter.py          ← v4에서 삭제 (Phase 0.5 + Phase 1이 대체)
├── orchestrator.py                     ← v4에서 ProjectOrchestrator로 재설계
├── packet/packet_builder.py
├── planner/
│   ├── planner_config.py
│   ├── planner_schema.py
│   └── planner_service.py
├── planning/
│   ├── backward_planner.py
│   └── slice_queue.py
├── research/
│   ├── base.py
│   ├── brave_adapter.py
│   ├── evidence_bundle.py
│   ├── gemini_adapter.py
│   ├── gemini_deep_research_adapter.py
│   ├── gpt_research_adapter.py
│   ├── perplexity_adapter.py
│   ├── router.py                       ← v4에서 parallel_router.py 추가
│   ├── tavily_adapter.py
│   └── youtube_adapter.py              ← v4에서 삭제
├── reviewer/
│   ├── llm_reviewer.py
│   ├── review_gate.py
│   └── rule_checker.py
├── store/artifact_store.py             ← v4에서 스키마 확장 (하위호환)
├── utils/id_generator.py
├── verification/
│   ├── result_verifier.py
│   └── spec_alignment.py
└── web/app.py                          ← v4에서 Phase별 UI로 재작성
```

### 확정 스택 (v3 종료 시점)
| 구성 | 스택 | 상태 |
|------|------|------|
| Planner/Builder/Doc/Reviewer | OpenRouter (유료 모델) | ✅ |
| Research Primary | Gemini Deep Research | ✅ real |
| Research Secondary | GPT Deep Research (o4-mini-deep-research) | ✅ real |
| Research Tertiary | Perplexity (sonar) | ✅ real |
| Research Fallback | YouTube stub | ⚠️ v4에서 제거 |
| 저장소 | SQLite artifact_store SSOT | ✅ |
| 웹 UI | FastAPI + 진행 상태 표시 | ✅ |

### 환경변수 (v3 기준)
```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_PLANNER_MODEL=openai/gpt-5.4
OPENROUTER_BUILDER_MODEL=anthropic/claude-sonnet-4.6
OPENROUTER_DOC_MODEL=openai/gpt-5.4-mini
OPENROUTER_REVIEWER_MODEL=openai/gpt-5.4-mini
OPENAI_API_KEY=sk-...
GPT_RESEARCH_MODEL=o4-mini-deep-research
GPT_RESEARCH_TIMEOUT=600.0
GEMINI_API_KEY=AQ...
GEMINI_DEEP_RESEARCH_TIMEOUT=600.0
PERPLEXITY_API_KEY=pplx-...
CURSOR_API_KEY=crsr_...
INTERPRETER_USE_LLM=false
```

### 대표 run_id 이력
| 사례 | run_id | 결과 |
|------|--------|------|
| Day 36 완주 | run-207f32b7 | completed |
| Day 37 slice_issue | run-a4030431 | verification_failed (slice_issue) |
| Day 38 doc_issue | run-a4030431 | verification_failed (doc_issue) |

---

## 2. v4 진입 시점 원칙 전환

### 공식 해제 항목
| 항목 | v1~v3 | v4 |
|------|-------|-----|
| artifact_store 스키마 | 불변 | 확장 허용 |
| orchestrator/graph_flow | 전면 수정 금지 | 필요시 수정 |
| 2-track 분리 | 완전 분리 | Phase 6에서 연결 |
| silent fallback | 전면 금지 | 병렬 경로만 partial 허용 |
| 리팩터링 | 금지 | Phase 단위 재구성 허용 |

### 유지 항목 (불변)
- 단일 호출 경로 silent fallback 금지
- stub/real 구분 엄격
- artifact_store SSOT
- Cursor = Executor 고정

---

## 3. v4 목표 구조

### 7-Phase + Phase 0.5 워크플로우
```
사용자 입력
  ↓
Phase 0.5 · 처리 가능성 게이트
  ↓
Phase 1 · 서브주제 분해
  ↓
Phase 2 · 병렬 리서치 (subtopic 순차 + adapter 병렬)
  ↓
Phase 3 · 2문서 합성 (기반정보 + 목표 산출물)
  ↓
Phase 4 · AI 교차 감사 (구조 Claude + 균형 GPT + 사실 Gemini + 통합)
  ↓
Phase 5 · 사용자 검수 루프 (피드백 → 재작성 → 버전 이력)
  ↓
Phase 6 · 트랙 전환 결정
  ├─ 문서 완료 → 종료
  └─ 앱개발 → Phase 7 진입
  ↓
Phase 7 · 앱개발 실행
  ├─ 7a Claude Builder (기존 v3 planner→builder→review)
  └─ 7b Cursor Executor (기존 v3 approval→packet→execution→verify)
```

### 신규 컴포넌트 (v4에서 추가)
- `src/phases/phase_0_5_gate.py`
- `src/phases/phase_1_decompose.py`
- `src/research/parallel_router.py`
- `src/phases/phase_3_synthesize.py`
- `src/reviewer/cross_auditor.py`
- `src/phases/phase_5_feedback.py`
- `src/document/version_manager.py`
- `src/phases/phase_6_bridge.py`
- `src/phases/phase_7_app_dev.py` (기존 로직 호출 래퍼)

### DB 스키마 변경
- `projects` 테이블 신규
- `artifacts` 테이블에 컬럼 10개 추가 (모두 JSON)

---

## 4. 롤백 기준점

v4 구현 중 치명적 문제 발생 시, 이 스냅샷 시점(v3 Day 112 종료)으로 롤백합니다.

### 롤백 절차
```bash
# 1. 현재 .env 백업
cp .env .env.v4_backup

# 2. v3 브랜치 체크아웃 (또는 git tag day-112-end)
git checkout v3-baseline

# 3. DB 백업 복원
cp orchestrator_v1.db.v3_backup orchestrator_v1.db

# 4. 테스트 확인
pytest -v  # 411 passed 확인
```

### v4 진입 전 백업 필수
- `orchestrator_v1.db` → `orchestrator_v1.db.v3_backup`
- 현재 git 상태 → `git tag day-112-end`

---

## 5. v4 구현 Step 진행 상태

| Step | 작업 | 상태 |
|------|------|------|
| 1 | scope.md v4 선언 | **✅ 완료 (Day 113)** |
| 2 | DB 스키마 확장 | ⏳ 다음 |
| 3 | Phase 0.5 구현 | ⏳ |
| 4 | Phase 1 구현 | ⏳ |
| 5 | Phase 2 구현 | ⏳ |
| 6 | Phase 3 구현 | ⏳ |
| 7 | Phase 6 구현 + lane_selector/flow_router 제거 | ⏳ |
| 8 | Phase 5 구현 | ⏳ |
| 9 | Phase 4 구현 | ⏳ |
| 10 | Phase 7 재배치 | ⏳ |
| 11 | 웹 UI 재작성 | ⏳ |
| 12 | 레거시 제거 + 테스트 재작성 | ⏳ |

---

## 6. 확정 결정사항 (변경 금지 · scope.md v4 §8 참조)

| # | 항목 | 확정 |
|---|------|------|
| 1 | project_id ↔ run_id | 1 프로젝트 = N run |
| 2 | Phase 2 병렬 정책 | subtopic 순차 + adapter 병렬 |
| 3 | Phase 4 기본값 | ON + OFF 옵션 + 비용 경고 |
| 4 | Phase 5 버전 상한 | 저장 무제한, UI 최근 10개 |
| 5 | resume 단위 | 프로젝트 단위 |
| 6 | Phase 0.5 | 명시적 추가 |
| 7 | Phase 4 감사관 3인 | 구조 / 균형 / 사실 |
| 8 | Claude 역할 | Builder |
| 9 | Cursor 역할 | Executor |

---

**이 스냅샷은 Day 113 진입 시점에 확정됨.**
**v4 구현이 완료되면 snapshot_v4_final.md로 별도 기록.**
