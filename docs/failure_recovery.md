# Failure Recovery (Day 65~72 반영)

## 1. Cursor 자동 실행 실패

**조건:** `CURSOR_AUTO_MODE=true` + API 호출 실패 / timeout

**동작:** 에러 출력 후 수동 입력으로 자동 전환 (silent fallback 금지)

```
[자동 실행 실패] CURSOR_API_KEY not set — ...
자동 실행 실패 — 수동 입력으로 전환합니다.

changed_files (쉼표 구분): ...
```

**수동 복구:** `CURSOR_AUTO_MODE=false` 설정 후 재실행

---

## 2. 검증 실패 — slice_issue

**조건:** `changed_files` 비어있음 / `test_results` 없음 / `run_log` 없음

**CLI 동작:** 자동으로 현재 slice 재실행 대기

```python
from src.orchestrator import retry_current_slice
updated = retry_current_slice("orchestrator_v1.db", run_id)
```

---

## 3. 검증 실패 — doc_issue

**조건:** `changed_files`가 `target_files` 범위 밖

**CLI 동작:** target_files 교정 입력 요청 → 재동결 → 재패킷

```python
from src.orchestrator import reaudit_doc
updated = reaudit_doc("orchestrator_v1.db", run_id,
                      patched_target_files=["src/auth.py"])
```

---

## 4. 승인 거절

**상태:** `run_status = "rejected"` → 새 요청으로 재시작

---

## 5. API 호출 실패

### OpenRouter
```
401 → API 키 오류: https://openrouter.ai/settings/keys
402 → 크레딧 소진: https://openrouter.ai/credits
```

### Gemini
```
오류 → https://aistudio.google.com/apikey 확인
```

### Cursor Auto Mode
```
CURSOR_API_KEY 없음  → 에러 + 수동 fallback
timeout              → CursorTimeoutError + 수동 fallback
API 오류             → CursorExecutorError + 수동 fallback
```

---

## 빠른 상태 확인

```bash
python -c "import sqlite3; conn = sqlite3.connect('orchestrator_v1.db'); rows = conn.execute('SELECT run_id, run_status, approval_status FROM artifacts ORDER BY rowid DESC LIMIT 5').fetchall(); [print(r) for r in rows]"
```
