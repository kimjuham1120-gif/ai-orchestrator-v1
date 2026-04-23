# Step 14 · 코드 경량화 분석 리포트

> 작성 기준: 업로드된 11개 파일 + 프로젝트 컨텍스트
> 목적: 병합·삭제·단순화 가능한 부분을 식별해 **가벼운 코드 베이스**로 만들기
> 원칙: **기존 테스트 403 passed 깨지 않음**, Phase 6·7의 핵심 기능 유지

---

## 요약

| 등급 | 내용 | 예상 감소 |
|---|---|---|
| 🔴 높음 | v3 잔재 4곳 삭제 | ~150줄 + 타입 혼란 제거 |
| 🟡 중간 | 래퍼 계층 통합 3곳 | ~100줄 + 호출 추적 단순화 |
| 🟢 낮음 | 헬퍼 통합·주석 정리 | ~50줄 + 가독성 |

**합계**: 약 300줄 감소 + 이해하기 쉬운 구조

삭제 전 반드시 `pytest` 로 회귀 확인. 각 항목마다 **테스트 영향도** 명시.

---

## 🔴 높음 — v3 잔재 제거

### 1. `graph_flow.py` — `OrchestratorState` v3 호환 필드 정리

**현재**: `OrchestratorState`에 **v3 시절 필드 8개**가 남아있음

```python
# v3 호환 필드 (사용 안 함)
research_bundle:     dict
initial_document:    dict
cross_audit_result:  dict
canonical_doc:       dict
canonical_frozen:    bool
deliverable_spec:    dict      # ← Phase 7에서만 필요, 나머지는 진짜 unused
slice_plan:          dict
current_slice_index: int
doc_only_mode:       bool
```

**현실**: 주석에 "Phase 0.5~6으로 대체됨"이라고 명시. `build_phase_7_graph()`는 `raw_input`, `deliverable_spec`, `task_type` 만 쓴다.

**액션**:
- `research_bundle`, `initial_document`, `cross_audit_result`, `canonical_doc`, `canonical_frozen`, `slice_plan`, `current_slice_index`, `doc_only_mode` → **삭제**
- `deliverable_spec` 만 유지 (Phase 6 → 7 브리지 데이터)

**감소**: 약 15줄, 하지만 더 중요한 건 **State 타입 혼란 제거**

**테스트 영향**: Phase 7 테스트가 이 필드들을 참조하지 않는다면 안전. 참조 시 → **실제로 값이 쓰이는지** 확인 후 결정.

**검증 명령**:
```powershell
# 실제로 참조하는 곳이 있는지 grep
Select-String -Path src\**\*.py -Pattern "research_bundle|initial_document|cross_audit_result|canonical_doc|canonical_frozen|slice_plan|current_slice_index|doc_only_mode" -Recurse
```
결과가 `graph_flow.py`만 나오면 → 전부 삭제 안전.

---

### 2. `artifact_store.py` — v3 전용 JSON 컬럼 deprecate 표시

**현재**: `_JSON_COLS_V3` 에 23개, `_JSON_COLS_V4` 에 8개.

```python
_JSON_COLS_V3 = {
    "research_bundle", "initial_document", "cross_audit_result",
    "canonical_doc", "deliverable_spec", "slice_plan",
    "plan", "selected_models", "builder_output",
    "rule_check_result", "llm_review_result", "reviewer_feedback",
    "execution_result", "execution_packet",
    "result_verification", "spec_alignment",
}
```

이 중 Phase 7이 **실제로 쓰는 것**:
- ✅ `deliverable_spec`, `plan`, `selected_models`, `builder_output`
- ✅ `rule_check_result`, `llm_review_result`, `reviewer_feedback`
- ✅ `execution_result`, `execution_packet`, `result_verification`, `spec_alignment`

**불필요 후보** (Phase 4~6이 대체):
- ❌ `research_bundle` — Phase 2 `parallel_research`가 대체
- ❌ `initial_document` — Phase 3 `base_info_doc` / `target_doc`이 대체
- ❌ `cross_audit_result` — Phase 4 `cross_audit_v4`가 대체
- ❌ `canonical_doc` — Phase 5 `doc_versions`가 대체
- ❌ `slice_plan` — v3 slice 기반 접근 (v4는 1 run = 전체 spec)

**액션**: 3단계로 분리
1. **즉시 가능**: 주석에 `# DEPRECATED - v3 only, TODO: remove Day 130+` 추가
2. **1주 관찰**: 테스트 돌려보며 실제 참조 여부 확인
3. **확정되면**: 컬럼 자체는 남기되(기존 DB 호환) Python 로직·mapping에서 제거

**테스트 영향**: 컬럼 삭제는 기존 DB 마이그레이션 필요 → **보류 권장**. deprecate 주석만 추가.

---

### 3. `orchestrator.py` — `create_packet_if_approved` 이중 artifact 로드

**현재**:
```python
def create_packet_if_approved(db_path, base_dir, run_id, goal, approval_status):
    if approval_status != "approved":
        return {...}
    
    artifact = load_artifact(db_path, run_id=run_id)          # 로드 1
    spec = artifact.get("deliverable_spec") if artifact else None
    
    packet = build_execution_packet(...)
    packet_path = write_packet_file(...)
    
    update_artifact(db_path, run_id, {...})                   # 업데이트 2
```

**문제**:
- 호출자(`handle_phase_7_packet`)가 이미 artifact를 가지고 있을 가능성 높음 → **중복 DB 읽기**
- `approval_status` 를 인자로 받는데 **DB에도 있음** → 인자에서 제거 가능

**간소화**:
```python
def create_packet_if_approved(db_path, base_dir, run_id, goal):
    artifact = load_artifact(db_path, run_id=run_id)
    if not artifact:
        return {"packet_created": False, "error": "artifact_not_found"}
    if artifact.get("approval_status") != "approved":
        return {"packet_created": False, "error": "approval_not_granted"}
    
    spec = artifact.get("deliverable_spec")
    # ... 나머지 동일
```

**감소**: 8줄 + 함수 시그니처 파라미터 1개 제거

**테스트 영향**: 이 함수의 시그니처 변경 → `handle_phase_7_packet` 도 수정. 테스트 존재 시 수정 필요.

---

### 4. `cli.py` — 실질 동작 없는 코드

**현재**:
```python
def main() -> None:
    print("웹 UI로 접속하세요:")
    print("  uvicorn src.web.app:app --reload")
    ...
```

**문제**:
- 순수 print 8줄 + docstring 10줄 = 30줄을 차지하지만, 실제 값은 없음
- 사용자 입장에서 `python -m src.cli` 치면 안내만 보고 결국 uvicorn 실행 필요

**선택지**:
- **A**: 파일 자체 삭제 → `python -m src.cli` 가 실패해도 무방 (웹 UI가 메인)
- **B**: 실제 기능 부여 → `python -m src.cli` 가 uvicorn을 자동 실행

**권장 B** (3줄로 대체):
```python
import subprocess, sys

def main() -> None:
    subprocess.run([sys.executable, "-m", "uvicorn", "src.web.app:app", "--reload"])

if __name__ == "__main__":
    main()
```

**감소**: 20줄 → 3줄

**테스트 영향**: 거의 없음 (CLI 테스트가 있다면 업데이트 필요).

---

## 🟡 중간 — 래퍼 계층 통합

### 5. `orchestrator.py` + `finalize_service.py` 통합

**현재 구조**:
```
web/handlers.py::handle_phase_7_finalize
  → orchestrator.py::finalize_run_step       (3줄 래퍼)
    → finalize_service.py::finalize_run      (실제 로직 15줄)
```

**문제**: `finalize_run_step` 은 그냥 `finalize_run`을 호출하는 **얇은 래퍼**

```python
def finalize_run_step(db_path, run_id, goal, approval_status, changed_files, test_results, run_log):
    from src.finalize.finalize_service import finalize_run
    return finalize_run(
        db_path=db_path, run_id=run_id, goal=goal, approval_status=approval_status,
        changed_files=changed_files, test_results=test_results,
        run_log=run_log,
    )
```

같은 시그니처로 그냥 전달만 함.

**액션**:
- `handlers.py` 에서 `finalize_run` 을 **직접 import**
- `orchestrator.py::finalize_run_step` 삭제
- `finalize_service.py::finalize_run` 만 유지

**감소**: 약 10줄 + **간접 호출 1단계 제거**

**테스트 영향**: `handlers.py` 수정 필요, 다른 테스트는 `finalize_run` 직접 테스트 중일 가능성 높아 안전.

---

### 6. `orchestrator.py::save_execution_result_step` 제거 후보

**현재**:
```python
def save_execution_result_step(db_path, run_id, changed_files, test_results, run_log):
    update_execution_result(db_path, run_id, changed_files, test_results, run_log)
```

**문제**: 함수 1줄. `update_execution_result`는 `artifact_store.py`에 이미 있음.

**액션**:
- `handlers.py::handle_phase_7_execution_result` 에서 `update_execution_result` 직접 호출
- `save_execution_result_step` 삭제

**감소**: 3줄 + 호출 1단계

**테스트 영향**: 5번과 동일, handlers 한 줄 교체.

---

### 7. `orchestrator.py` 파일 자체의 존재 가치 재검토

**현재 `orchestrator.py` 는 4개 함수만**:
1. `create_packet_if_approved` → packet_builder 호출만
2. `save_execution_result_step` → artifact_store 호출만
3. `run_verification` → verifier + alignment 호출만
4. `finalize_run_step` → finalize_service 호출만

**이 파일은 "4개 함수를 한 곳에 모은 래퍼"**.

**선택지**:
- **A**: 4개 함수를 각각 원래 모듈로 분산 (`packet_builder.py`, `verification/`, `finalize/`)
- **B**: 현 상태 유지 (handlers가 한 모듈만 import하면 되는 편의)
- **C**: `run_verification`만 `verification/__init__.py` 로 옮기고, 나머지 3개는 삭제해서 handlers가 직접 호출

**권장 C**:
- `create_packet_if_approved` → packet_builder로 이동 (5번 수정과 함께)
- `save_execution_result_step` → 삭제 (6번)
- `finalize_run_step` → 삭제 (5번)
- `run_verification` 만 남기면 `orchestrator.py`는 1개 함수 → 그마저 `verification/` 안으로 이동 가능

→ **`orchestrator.py` 파일 자체 제거 가능**

**감소**: 파일 1개 + 전체 약 100줄

**테스트 영향**: handlers + verification 테스트 수정. 위험도 중간.

**권장 타이밍**: Step 14-1 (비용 추적) 끝나고, 리팩토링 전용 날에.

---

## 🟢 낮음 — 세부 정리

### 8. 중복 상태 관리 — `approval_required` + `approval_status`

**현재**: artifact_store 스키마에:
- `approval_required: INTEGER (bool)`
- `approval_status: TEXT`  ("pending", "approved", "rejected")
- `approval_reason: TEXT`

**문제**: `approval_required` 는 `approval_status == "pending"` 으로 유도 가능. 이중 진실 원천.

**액션**: `approval_required` 삭제, 조회 시 `status == "pending"` 으로 파생.

**감소**: 스키마 1컬럼 + 업데이트 로직 2~3곳

**테스트 영향**: 큼 — 이 컬럼 참조 테스트가 여러 개일 가능성. **보류 권장** (위험 대비 이득 작음).

---

### 9. `spec_alignment.py::STATUS_SKIPPED` 미정의 문제

**현재**: phase_3_synthesize 에서 `STATUS_SKIPPED = "skipped"` 정의. 
`spec_alignment.py` 의 `AlignmentResult.failure_type` 은 `"slice_issue" | "doc_issue" | None` — **v3의 slice 용어 남음**.

**문제**: `"slice_issue"`는 v4에 없는 개념 (slice_plan 안 쓰니까).

**액션**:
- `"slice_issue"` → `"missing_required_fields"` 로 이름 변경
- `"doc_issue"` → `"out_of_scope"` 로 이름 변경
- 주석에서 slice 관련 설명 제거

**감소**: 줄 수는 동일, **의미 명확화**

**테스트 영향**: 문자열 비교하는 테스트가 있으면 수정 필요.

---

### 10. `llm_utils.py::clean_markdown_wrapper` 활용 저조

**현재**: `clean_markdown_wrapper`가 정의되어 있고 `call_llm` 내부에서 자동 호출.

**확인 필요**: phase_5, phase_3 파일에서 `from src.utils.llm_utils import call_llm, clean_markdown_wrapper` 로 **둘 다 import** 하지만 `clean_markdown_wrapper`는 안 씀.

**액션**: 사용 안 하는 import 제거.

**검증 명령**:
```powershell
Select-String -Path src\phases\*.py -Pattern "clean_markdown_wrapper" -SimpleMatch
```

각 파일에서 import만 하고 실제 호출 없으면 → import 정리.

**감소**: 파일당 1줄 × 5개 Phase = 5줄

**테스트 영향**: 없음.

---

### 11. `result_verifier.py` + `spec_alignment.py` 병합 검토

**현재**:
- `result_verifier.py` — execution_result 기본 검증 (30줄)
- `spec_alignment.py` — spec과 매칭 검증 (50줄)
- 둘 다 `run_verification` 에서만 호출됨
- 둘 다 유사한 dataclass 패턴

**액션**:
- `src/verification/__init__.py` 에 둘을 묶고 단일 `verify(exec_result, spec)` API 제공
- 내부에서 두 검증 수행 후 합친 결과 반환

**감소**: 분리 이득 없는 2파일 → 1파일 합병 (약 20줄 감소)

**테스트 영향**: 두 모듈 분리해서 테스트했으면 통합 테스트로 전환 필요. 중간 위험.

**권장 타이밍**: Step 14-5 (체크포인트) 와 함께 검증 로직 전반 리팩토링 시.

---

## 📋 실행 로드맵

### Phase A · 안전한 정리 (1일, Step 14-1 들어가기 전)
완료 조건: pytest 403 passed 유지.

1. **#10 미사용 import 제거** (5분)
2. **#4 cli.py 실제 동작 부여** (10분)
3. **#1 graph_flow.py v3 필드 삭제** (30분, grep 검증 후)
4. **#9 spec_alignment 용어 현대화** (20분)
5. **#3 create_packet_if_approved 단순화** (20분)

**예상 감소**: 약 70줄

### Phase B · 래퍼 통합 (0.5일, Step 14-2 병행)
완료 조건: pytest 403 passed 유지.

6. **#5 finalize 래퍼 제거** (30분)
7. **#6 save_execution_result_step 삭제** (20분)

**예상 감소**: 약 15줄

### Phase C · 구조 재편 (1일, Step 14-5와 함께)
완료 조건: pytest 440+ passed (Step 14 완료 시점).

8. **#7 orchestrator.py 파일 제거** (판단 후)
9. **#11 verification 통합**
10. **#2 v3 컬럼 deprecate 주석** (실제 삭제는 v5)

**예상 감소**: 약 200줄 + 파일 1개

### Phase D · 보류 (위험 대비 이득 작음)
- **#8 approval_required/status 통합** — 수정 범위 크고 이득 작음
- **#2 컬럼 실제 삭제** — 마이그레이션 필요, DB 호환 영향

---

## ⚠️ 주의 사항

### DO
- 각 항목마다 **grep 또는 tests 돌려 참조 확인 후** 수정
- 커밋은 **항목별 분리** (롤백 쉽도록)
- 수정 전 `pytest` → 수정 후 `pytest` 각각 기록
- PR 단위 또는 하루 단위로 푸시

### DON'T
- Step 14-1 (비용 추적) 구현과 **동시 진행 금지** — 변경 원인 추적 어려움
- v3 컬럼을 **DB에서 실제 삭제** — 기존 DB 호환 깨짐
- `orchestrator.py` 파일 **전면 제거를 단일 커밋**으로 — 점진 권장

---

## Next

이 리포트 반영 후 **병합·삭제 완료된 v4 코드**에 대해:
- 최종 pytest 통과 수 (403 + Step 14 신규 테스트)
- 소스 라인 수 감소 측정 (before/after LOC)
- 모듈 의존성 그래프 재검토

Step 14 작업 후 `step_14_refactor_result.md` 로 결과 기록 권장.

---

## 변경 이력
- **v1** (현재): 업로드 파일 11개 기준 분석. Phase A~D 로드맵 제안.
- **v2** (예정): 작업 PC에서 전체 소스 grep 후 정밀 분석 (현재는 11개 파일만 봄)
