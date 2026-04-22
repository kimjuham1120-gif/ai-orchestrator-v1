# ai-orchestrator-v4 프로젝트 컨텍스트 (Day 123)

## 현재 상태
- pytest: **403 passed / 0 failed** ✅
- Step 13 (강화/최적화) **완료** — tag: `v4.13-done`
- 다음: Step 14 (비용 추적 → Phase 2 병렬 → SSE)

## Step 진행 이력
```
Step 1  ✅ scope.md v4
Step 2  ✅ DB 스키마 (+27)
Step 3  ✅ Phase 0.5 (+41)
Step 4  ✅ Phase 1   (+27)
Step 5  ✅ Phase 2   (+19)
Step 6  ✅ Phase 3   (+26)
Step 7  ✅ Phase 6   (+39)
Step 8  ✅ Phase 5   (+42)
Step 9  ✅ Phase 4   (+26)
Step 10 ✅ Phase 7   (+31)
Step 11 ✅ 웹 UI MVP (+18)
Step 12 ✅ 레거시 제거 (287개 v3 테스트 삭제)
Step 13 ✅ 강화/최적화 (403 passed 달성)
Step 14 ⏳ 계획 수립 완료 (step_14_plan.md), 착수 대기
```

## 7-Phase 워크플로우 (확정)
```
Phase 0.5 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7
게이트      서브주제   병렬리서치  2문서합성   3감사관    검수루프    트랙결정    앱개발
```

## 3감사관 구성 (변경 금지)
| 감사관 | 모델 | 역할 |
|--------|------|------|
| 구조 감사관 | anthropic/claude-opus-4.7 | 논리 구조 |
| 균형 감사관 | openai/gpt-5.4 | 편향 중립화 |
| 사실 감사관 | google/gemini-3.1-pro-preview | 사실 검증 |
| 통합 LLM | openai/gpt-5.4 | 고도화 편집 |

## 파일 구조 (v4)
```
src/
  phases/phase_0_5_gate.py, phase_1_decompose.py, phase_2_*.py
         phase_3_synthesize.py, phase_4_audit.py
         phase_5_feedback.py, phase_6_bridge.py, phase_7_app_dev.py
  utils/llm_utils.py (Step 13 완료), id_generator.py
  store/artifact_store.py (projects + artifacts 테이블)
  web/app.py, handlers.py, templates/, static/
  graph_flow.py (build_phase_7_graph만)
  orchestrator.py (4개 함수만)
  cli.py (최소 v4)
tests/ (403 passed)
docs/
  step_14_plan.md
README.md
```

## Step 13 완료 내역

### 핵심 산출물
1. **src/utils/llm_utils.py**
   - `call_llm(prompt, model, timeout, use_cache=True)`
   - 4000자 이상 프롬프트에 `cache_control: ephemeral` (Claude 90%, GPT 50% 할인)
   - Exponential backoff 재시도: 최대 2회, 1s/2s 대기
   - 4xx / 타임아웃 → 재시도 없음
   - `httpx` 모듈 상단 import (patch 가능하도록)

2. **DB 인덱스 5개** (artifact_store.py)

3. **Phase 0.5/1/3/4/5 → call_llm 교체 완료**

4. **Phase 3·5 상수 정의 복원**
   - `SYNTHESIS_MODEL`, `SYNTHESIS_TIMEOUT`
   - `FEEDBACK_MODEL`, `FEEDBACK_TIMEOUT`

5. **테스트 수정 완료**
   - test_day120 (Phase 4) — 재작성
   - test_day119 (Phase 5) — 재작성
   - test_day117 (Phase 3) — call_llm 직접 mock 방식으로 전환
   - test_day123 (llm_utils) 신규 18개

### 테스트 통과 이력
- Step 13 시작: 380 passed / 23 failed
- 중간: 396 passed / 7 failed (test_day117만 남음)
- **최종: 403 passed / 0 failed** ✅

## 환경
- OS: Windows PowerShell
- Python: 3.14, .venv
- 경로: C:\Users\MSI\Desktop\ai-orchestrator-v1
- DB: orchestrator_v1.db (SQLite)

## 환경변수
| 변수 | 기본값 | 용도 |
|---|---|---|
| OPENROUTER_API_KEY | (필수) | LLM 호출 |
| PROMPT_CACHE_ENABLED | true | 캐싱 on/off |
| PHASE_4_ENABLED | true | 3감사관 사용 |
| FEEDBACK_MODEL | openai/gpt-5.4 | Phase 5 |
| FEEDBACK_TIMEOUT | 90.0 | Phase 5 |
| SYNTHESIS_MODEL | openai/gpt-5.4 | Phase 3 |
| SYNTHESIS_TIMEOUT | 90.0 | Phase 3 |

## 작업 방식 (사용자 선호)
- 항상: 수정 대상 → 구현 → 테스트 → 실행법 순서
- 파일 수정: 사용자 업로드 → Claude 수정 → outputs 전달
- pytest 결과: 마지막 5줄만 공유
- 짧고 명료한 지시 ("ㄱ", 파일명만 등)
- 비용·복잡도 민감

## 핵심 결정사항 (변경 금지)
- 1 project = N runs (project_id ↔ run_id)
- Phase 4 기본 ON (PHASE_4_ENABLED=true)
- 캐싱 기본 ON (PROMPT_CACHE_ENABLED=true)
- SQLite SSOT
- Cursor = Executor (수동 handoff 유지)

## 패치 방식 표준 (Step 13 확정)
테스트에서 LLM 호출 mock은 **call_llm 직접 patch**:
```python
# src/phases/phase_X.py 가 `from src.utils.llm_utils import call_llm` 한 경우
_CALL_LLM_PATCH = "src.phases.phase_X.call_llm"
with patch(_CALL_LLM_PATCH, side_effect=["응답1", "응답2"]):
    ...
```
**httpx 직접 patch는 사용하지 않음** — 재시도 로직과 충돌.

## 다음 단계: Step 14
`docs/step_14_plan.md` 참조.

### 권장 순서
1. **비용 추적** (Phase 2 병렬 전후 비교 기준선 확보)
2. **Phase 2 병렬 확대**
3. **웹 UI SSE**

### 예상 소요
- 비용 추적: 2.5일
- Phase 2 병렬: 1.5일
- SSE: 2일
- 합계 6일 (+ 버퍼 2일)
