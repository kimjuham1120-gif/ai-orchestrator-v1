# Runbook — ai-orchestrator-v2 (Day 73~80 확정)

## 1. 정상 실행 흐름

### 자동 모드 (CURSOR_AUTO_MODE=true)

```
사용자 입력
  → classify (5분류)
  → research (Gemini Deep Research + GPT Deep Research + Perplexity)
  → initial_doc → cross_audit → canonical_freeze
  → deliverable_spec → backward_plan
  → planner → builder → 3-layer review → approval_prepare
  → [사용자 승인]
  → packet_generate
  → Cursor Background Agent 자동 호출 → polling → execution_result 자동 수집
  → result_verify → spec_alignment
  → finalize
```

### 수동 모드 (CURSOR_AUTO_MODE=false, 기본)

```
사용자 입력
  → ... (동일)
  → [사용자 승인]
  → packet_generate → packet 파일 경로 출력
  → 사용자가 Cursor에 붙여넣기 → 실행
  → changed_files / test_results / run_log 수동 입력
  → result_verify → spec_alignment → finalize
```

---

## 2. run_status 상태표

| 상태 | 의미 | 다음 액션 |
|------|------|-----------|
| `classified` | 분류 완료 | 자동 진행 |
| `doc_frozen` | 문서 고정 중단 | `resume_from_doc` |
| `waiting_approval` | 사용자 승인 대기 | approve / reject |
| `approved` | 승인됨 | `create_packet_if_approved` |
| `packet_ready` | 패킷 생성됨 | Cursor 실행 (자동/수동) |
| `execution_result_received` | 결과 수신 | `run_verification` |
| `verified` | 검증 통과 | `finalize_run_step` |
| `verification_failed` | 검증 실패 | 실패 유형별 복구 |
| `rejected` | 사용자 거절 | 종료 또는 재시작 |
| `failed` | unsupported 요청 | 종료 |
| `completed` | 완료 | — |

---

## 3. execution_result 입력 규칙

| 필드 | 필수 | 실패 조건 |
|------|------|-----------|
| `changed_files` | ✅ | 비어있으면 `slice_issue` |
| `test_results` | ✅ | 비어있거나 `failed` 포함 시 실패 |
| `run_log` | ✅ | 비어있으면 `slice_issue` |

---

## 4. 검증 실패 분기

| `failure_type` | 원인 | CLI 동작 |
|----------------|------|----------|
| `slice_issue` | 결과 필드 누락 / 테스트 실패 | 자동 slice 재실행 |
| `doc_issue` | changed_files가 target_files 범위 밖 | target_files 교정 입력 요청 |

---

## 5. API 키 상태 확인

```powershell
python -c "
from dotenv import load_dotenv; load_dotenv(); import os
keys = {
    'OPENROUTER_API_KEY': 'planner/builder',
    'GEMINI_API_KEY': 'Gemini Deep Research',
    'OPENAI_API_KEY': 'GPT Deep Research',
    'PERPLEXITY_API_KEY': 'Perplexity support',
    'CURSOR_API_KEY': 'Cursor 자동 실행',
}
for k, v in keys.items():
    print(f'{v}: {\"OK\" if os.environ.get(k) else \"MISSING/inactive\"}')"
```

---

## 6. Cursor 모드 확인

```powershell
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print('Cursor mode:', os.environ.get('CURSOR_AUTO_MODE', 'false'))"
```

---

## 7. DB 조회

```powershell
python -c "import sqlite3; conn = sqlite3.connect('orchestrator_v1.db'); rows = conn.execute('SELECT run_id, run_status, task_type FROM artifacts ORDER BY rowid DESC LIMIT 5').fetchall(); [print(r) for r in rows]"
```

---

## 8. DB 초기화 (주의: 데이터 삭제)

```powershell
del orchestrator_v1.db        # Windows
# rm orchestrator_v1.db       # macOS/Linux
```

---

## 9. 테스트 실행

```powershell
.venv\Scripts\activate
pytest -v --timeout=30   # 294 passed 확인
```
