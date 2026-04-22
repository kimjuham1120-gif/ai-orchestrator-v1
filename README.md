# ai-orchestrator-v4

> 개인 개발 메모 · 복기용 README
> 최종 갱신: Day 123, Step 13 진행 중

---

## 현재 상태 (한눈에)

- pytest: **396 passed / 7 failed** (목표 403)
- 실패: `tests/test_day117_phase_3.py` 7개만 남음 (패치 경로 수정 필요)
- 진행 중: Step 13 (강화/최적화) — LLM utils / 캐싱 / 재시도 완료, 테스트 정리 중
- 코어 파이프라인(Phase 0.5 ~ 7): 완성

---

## 빠른 실행

```powershell
# 1. 환경
cd C:\Users\MSI\Desktop\ai-orchestrator-v1
.venv\Scripts\activate

# 2. 환경변수 (최소)
$env:OPENROUTER_API_KEY = "sk-or-..."

# 3. 웹 UI
uvicorn src.web.app:app --reload
# → http://localhost:8000

# 4. 테스트
pytest --tb=no -q 2>&1 | Select-Object -Last 5
```

### 선택 환경변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `OPENROUTER_API_KEY` | (필수) | LLM 호출 |
| `PROMPT_CACHE_ENABLED` | `true` | 캐싱 on/off |
| `PHASE_4_ENABLED` | `true` | 3감사관 사용 여부 |
| `FEEDBACK_MODEL` | `openai/gpt-5.4` | Phase 5 |
| `FEEDBACK_TIMEOUT` | `90.0` | Phase 5 |
| `SYNTHESIS_MODEL` | `openai/gpt-5.4` | Phase 3 |
| `SYNTHESIS_TIMEOUT` | `90.0` | Phase 3 |

---

## 7-Phase 파이프라인

```
Phase 0.5 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7
게이트      서브주제   병렬리서치  2문서합성   3감사관    검수루프    트랙결정    앱개발
```

| Phase | 파일 | 하는 일 |
|---|---|---|
| 0.5 | `phase_0_5_gate.py` | 실행 가능성 게이트 |
| 1 | `phase_1_decompose.py` | 요청 → 서브주제 N개 |
| 2 | `phase_2_*.py` | 서브주제 병렬 리서치 |
| 3 | `phase_3_synthesize.py` | 2문서 동시 합성 (3a=기반정보, 3b=목표산출물) |
| 4 | `phase_4_audit.py` | 3감사관 병렬 검수 |
| 5 | `phase_5_feedback.py` | 피드백 루프 + 버전 관리 |
| 6 | `phase_6_bridge.py` | 앱개발 vs 문서 트랙 결정 |
| 7 | `phase_7_app_dev.py` | planner → builder → review_gate → approval |

### 3감사관 구성 (변경 금지)

| 감사관 | 모델 | 역할 |
|---|---|---|
| 구조 | `anthropic/claude-opus-4.7` | 논리 구조 |
| 균형 | `openai/gpt-5.4` | 편향 중립화 |
| 사실 | `google/gemini-3.1-pro-preview` | 사실 검증 |
| 통합 | `openai/gpt-5.4` | 고도화 편집 |

---

## 프로젝트 구조

```
src/
  phases/
    phase_0_5_gate.py
    phase_1_decompose.py
    phase_2_*.py
    phase_3_synthesize.py
    phase_4_audit.py
    phase_5_feedback.py
    phase_6_bridge.py
    phase_7_app_dev.py
  utils/
    llm_utils.py          ← Step 13 신규 (공통 LLM 호출)
    id_generator.py
  store/
    artifact_store.py     ← SQLite SSOT (projects + artifacts)
  web/
    app.py                ← FastAPI 진입점
    handlers.py
    templates/
    static/
  verification/
    result_verifier.py
    spec_alignment.py
  finalize/
    finalize_service.py
  graph_flow.py           ← Phase 7 LangGraph만 (v3 제거됨)
  orchestrator.py         ← 4개 함수만 (Phase 7 래퍼)
  cli.py                  ← 웹 UI 안내만

tests/                    ← 403 target, 현재 396 passing
orchestrator_v1.db        ← SQLite (gitignore)
```

---

## 핵심 결정사항 (변경 금지)

1. **1 project = N runs** (project_id ↔ run_id)
2. **Phase 4 기본 ON** (PHASE_4_ENABLED=true)
3. **캐싱 기본 ON** (PROMPT_CACHE_ENABLED=true)
4. **SQLite SSOT** — 다른 저장소로 옮기지 않음
5. **Cursor = Executor** — 수동 handoff 유지 (Phase 7 → 외부 실행)
6. **버전 저장 무제한**, UI 표시만 최근 10개 (`get_recent_versions`)

---

## Step 진행 이력

```
Step 1  ✅ scope.md v4
Step 2  ✅ DB 스키마 (+27 tests)
Step 3  ✅ Phase 0.5 (+41)
Step 4  ✅ Phase 1   (+27)
Step 5  ✅ Phase 2   (+19)
Step 6  ✅ Phase 3   (+26)
Step 7  ✅ Phase 6   (+39)
Step 8  ✅ Phase 5   (+42)
Step 9  ✅ Phase 4   (+26)
Step 10 ✅ Phase 7   (+31)
Step 11 ✅ 웹 UI MVP (+18)
Step 12 ✅ 레거시 제거 (v3 테스트 287개 삭제)
Step 13 ⏳ 강화/최적화 (진행 중)
Step 14 ❌ Phase 2 병렬 확대 / 비용 추적 / SSE (계획)
```

---

## Step 13 상세

### 완료
- `src/utils/llm_utils.py` 신규
  - `call_llm(prompt, model, timeout, use_cache=True)`
  - 4000자 이상 프롬프트에 `cache_control: ephemeral`
  - Exponential backoff: 최대 2회, 1s/2s 대기
  - 4xx / 타임아웃 → 재시도 없음
- DB 인덱스 5개 추가 (artifact_store.py)
- Phase 0.5/1/3/4/5 → `call_llm` 교체 완료
- test_day120 (Phase 4) 재작성 완료
- test_day119 (Phase 5) 재작성 완료
- test_day123 (llm_utils) 신규 18개 통과

### 남음
- test_day117 (Phase 3) 7개 패치 경로 수정
- Phase 2 병렬 확대 → Step 14
- 비용 추적 → Step 14
- 웹 UI SSE → Step 14

---

## 자주 밟는 함정

### 1. patch 경로
```python
# 틀림 — 동작 안 함
with patch.object(httpx, "post", return_value=mock):

# 맞음
with patch("src.utils.llm_utils.httpx.post", return_value=mock):
```

### 2. content 형식 (캐싱 on일 때)
```python
# messages[0]["content"]가 str 이 아닌 list일 수 있음
def _get_text(kwargs):
    msg = kwargs["json"]["messages"][0]["content"]
    if isinstance(msg, list):
        return msg[0].get("text", "")
    return msg
```

### 3. call_llm 시그니처
```python
# 틀림
call_llm(prompt)

# 맞음 — 모델/타임아웃은 모듈 상수에서
call_llm(prompt, FEEDBACK_MODEL, FEEDBACK_TIMEOUT)
```

### 4. httpx import 위치
```python
# llm_utils.py 상단에 있어야 patch 가능
import httpx  # ← 모듈 레벨 필수
```

---

## DB 스키마 요약

### projects
- project_id (PK), title, raw_input
- created_at, updated_at, current_phase, status

### artifacts
- run_id (PK), thread_id, project_id, phase
- 각 Phase 결과 (JSON): feasibility_result, subtopics, parallel_research,
  base_info_doc, target_doc, cross_audit_v4, doc_versions, feedback_history,
  bridge_decision
- Phase 7 결과: plan, builder_output, reviewer_feedback, execution_packet,
  execution_result, final_summary
- 메타: run_status, last_node, error, approval_status

JSON 컬럼은 `serialize/deserialize`로 자동 변환. 빈 문자열은 NULL로 저장.

---

## 작업 스타일 메모

- 짧고 명료한 지시 선호
- 수정 대상 파일 목록 → 구현 순서 → 코드 → 테스트 → 실행법 순서
- pytest 결과는 마지막 5줄만 공유
- 비용·복잡도 민감 → 불필요한 리팩터 지양
- 기존 baseline 건드리지 않고 **남은 미완성만** 보강

---

## 다음 액션

1. test_day117_phase_3.py 패치 경로 수정 → 403 passed
2. Step 14 시작 (별도 `step_14_plan.md` 참조)
