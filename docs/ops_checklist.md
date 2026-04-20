# 운영 체크리스트 — ai-orchestrator-v2 (Day 73~80 확정)

---

## 1. 시작 전 필수 확인

```powershell
.venv\Scripts\activate

python -c "
from dotenv import load_dotenv; load_dotenv(); import os
checks = [
    ('OPENROUTER_API_KEY', 'planner/builder', True),
    ('GEMINI_API_KEY', 'Gemini Deep Research', True),
    ('OPENAI_API_KEY', 'GPT Deep Research', False),
    ('PERPLEXITY_API_KEY', 'Perplexity support', False),
    ('CURSOR_API_KEY', 'Cursor 자동 실행', False),
]
for k, label, required in checks:
    status = 'OK' if os.environ.get(k) else ('MISSING' if required else 'inactive')
    print(f'{label}: {status}')
print('Cursor mode:', os.environ.get('CURSOR_AUTO_MODE', 'false'))
"
```

---

## 2. 새 요청 실행 순서

```
python -m src.cli
→ 1. 새 요청
→ 요청 입력 (예: "로그인 버그 수정해줘")
→ 문서 고정까지만? n
→ 승인: approve
→ [자동 모드] Cursor 자동 실행 → 완료 대기
  [수동 모드] packet 파일 → Cursor 붙여넣기 → 결과 입력
→ completed 확인
```

---

## 3. resume 방법

```powershell
python -c "import sqlite3; conn = sqlite3.connect('orchestrator_v1.db'); rows = conn.execute('SELECT run_id, run_status FROM artifacts ORDER BY rowid DESC LIMIT 5').fetchall(); [print(r) for r in rows]"

python -m src.cli → 2. 기존 실행 재개 → run_id 입력
```

---

## 4. 실패 시 복구

| 실패 유형 | CLI 동작 | 수동 복구 |
|-----------|----------|-----------|
| `slice_issue` | 자동 slice 재실행 | `retry_current_slice(db, run_id)` |
| `doc_issue` | target_files 교정 입력 | `reaudit_doc(db, run_id, [...])` |
| Cursor 자동 실패 | 수동 입력으로 전환 | `CURSOR_AUTO_MODE=false` |
| `rejected` | 종료 | 새 요청 |
| `unsupported` | 종료 | 키워드 포함 재입력 |

---

## 5. 테스트 실행

```powershell
pytest -v --timeout=30    # 294 passed 확인
pytest -v --timeout=30 -q  # 빠른 확인
```

---

## 6. v2 종료 기준 체크

```
[ ] 294 passed
[ ] GEMINI_API_KEY OK
[ ] OPENROUTER_API_KEY OK
[ ] GPT research claims 확인 (smoke test)
[ ] Perplexity claims 확인 (smoke test)
[ ] approval → packet → result → verify → finalize 1회 완주
```
