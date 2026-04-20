# Resume Flow — doc_frozen 상태에서 재개

## 언제 사용하나

`doc_only=True`로 실행하면 문서 고정(`canonical_freeze`) 직후 중단되고  
`run_status = "doc_frozen"`이 됩니다.

나중에 실행 계획 단계부터 이어서 진행할 때 resume을 사용합니다.

---

## CLI로 resume

```
=== AI Orchestrator v1 ===
1. 새 요청
2. 기존 실행 재개 (resume)
선택 (1/2): 2
run_id 입력: run-abc123
```

CLI가 `run_status`를 감지하고 자동으로 적절한 분기를 실행합니다.

---

## 코드로 직접 resume

```python
from src.orchestrator import run_orchestration, resume_from_doc
from src.store.artifact_store import load_artifact

# 1단계: doc_only 실행
result = run_orchestration("버그 수정해줘", "my.db", doc_only=True)
run_id = result["run_id"]
# result["run_status"] == "doc_frozen"

# ... 나중에 ...

# 2단계: resume
updated = resume_from_doc("my.db", run_id)
# updated["run_status"] == "waiting_approval"
# updated["plan"], updated["builder_output"] 생성됨
```

---

## 상태 전이

```
doc_frozen
  └─ resume_from_doc()
       └─ deliverable_spec → backward_plan → planner → builder
            → review_gate → approval_prepare
                 └─ waiting_approval
```

---

## resume 가능 상태 목록

| run_status | resume 방식 |
|------------|-------------|
| `doc_frozen` | `resume_from_doc()` |
| `waiting_approval` | `apply_user_approval()` → approve/reject |
| `approved` / `packet_ready` | `create_packet_if_approved()` |
| `execution_result_received` | `run_verification()` |

`doc_frozen`이 아닌 상태에서 `resume_from_doc()`을 호출하면  
`ValueError: run_status must be 'doc_frozen'`이 발생합니다.

---

## Slice 반복 resume

모든 slice를 순서대로 실행합니다.

```python
from src.orchestrator import run_next_slice, advance_current_slice

# 현재 slice 실행
updated = run_next_slice("my.db", run_id)

# 승인 → 실행 → 검증 후 다음 slice로 전진
result = advance_current_slice("my.db", run_id)
# result["has_remaining"] == True/False
```
