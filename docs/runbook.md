# Runbook — ai-orchestrator-v2 (Day 81~88 확정)

## 1. 실행 모드

### CLI 모드 (기존)
```powershell
.venv\Scripts\activate
python -m src.cli
```

### 웹 UI 모드 (신규)
```powershell
.venv\Scripts\activate
uvicorn src.web.app:app --reload --port 8000
# 브라우저: http://localhost:8000
```

CLI와 웹 UI는 동일한 `orchestrator_v1.db`를 사용. 병행 운영 가능.

---

## 2. 실행 흐름

### 자동 모드 (CURSOR_AUTO_MODE=true)
```
python -m src.cli → 요청 입력 → approve
  → Cursor 자동 실행 → execution_result 자동 수집 → verify → finalize
```

또는 웹 UI에서 approve:
```
http://localhost:8000 → run 클릭 → Approve 버튼
→ CLI 또는 다음 자동화 단계로 이어짐
```

### 수동 모드 (기본)
```
python -m src.cli → 요청 입력 → approve
  → packet 파일 → Cursor 수동 실행 → 결과 입력 → verify → finalize
```

---

## 3. run_status 상태표

| 상태 | 의미 | 다음 액션 |
|------|------|-----------|
| `classified` | 분류 완료 | 자동 진행 |
| `doc_frozen` | 문서 고정 중단 | `resume_from_doc` |
| `waiting_approval` | 승인 대기 | CLI approve 또는 웹 UI Approve 버튼 |
| `approved` | 승인됨 | `create_packet_if_approved` |
| `packet_ready` | 패킷 생성됨 | Cursor 실행 |
| `execution_result_received` | 결과 수신 | `run_verification` |
| `verified` | 검증 통과 | `finalize_run_step` |
| `verification_failed` | 검증 실패 | slice_issue / doc_issue 복구 |
| `rejected` | 거절 | 종료 |
| `failed` | unsupported | 종료 |
| `completed` | 완료 | — |

---

## 4. API 키 상태 확인

```powershell
python -c "
from dotenv import load_dotenv; load_dotenv(); import os
for k, v in [
  ('OPENROUTER_API_KEY','planner/builder'),
  ('GEMINI_API_KEY','Gemini Deep Research'),
  ('OPENAI_API_KEY','GPT Deep Research'),
  ('PERPLEXITY_API_KEY','Perplexity'),
  ('CURSOR_API_KEY','Cursor 자동'),
]: print(f'{v}: {\"OK\" if os.environ.get(k) else \"inactive\"}')"
```

---

## 5. DB 조회

```powershell
python -c "import sqlite3; conn=sqlite3.connect('orchestrator_v1.db'); [print(r) for r in conn.execute('SELECT run_id,run_status,task_type FROM artifacts ORDER BY rowid DESC LIMIT 5').fetchall()]"
```

---

## 6. 테스트

```powershell
pytest -v --timeout=30
```
