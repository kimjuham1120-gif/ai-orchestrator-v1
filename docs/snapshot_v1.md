# 스냅샷 — ai-orchestrator (Day 65~72 Cursor 자동화)

---

## 테스트 상태

```
목표: ~320 passed (292 기존 + ~28 신규)
신규: tests/test_day65_cursor_auto.py
경고: google-genai SDK DeprecationWarning — 무해
```

---

## 신규 파일

```
src/cursor/__init__.py
src/cursor/cursor_executor.py       ← Cursor Background Agent 자동 실행
src/cursor/cursor_result_adapter.py ← 결과 → execution_result 변환
src/cli.py                          ← 자동/수동 모드 분기 추가
tests/test_day65_cursor_auto.py     ← 신규 테스트
```

---

## 자동 실행 흐름

```
approve
  → create_packet_if_approved()
  → CURSOR_AUTO_MODE=true?
      Yes → CursorExecutor.execute()
              → POST /v1/background-agent/jobs
              → polling GET /v1/background-agent/jobs/{job_id}
              → CursorExecutionResult
              → adapt_cursor_result()
              → save_execution_result_step()
              → run_verification() → finalize()
      No / 실패 → 수동 입력 (기존 흐름)
```

---

## 환경변수 (Cursor 자동화)

```env
CURSOR_AUTO_MODE=true              # 자동 모드 활성화
CURSOR_API_KEY=cursor-...          # Background Agent API 키
CURSOR_REPO_PATH=./                # 실행 저장소 경로
CURSOR_EXECUTION_TIMEOUT=600.0     # 최대 대기
CURSOR_POLL_INTERVAL=10.0          # polling 간격
```

---

## 다음 구간

- Cursor API 실제 연동 검증 (smoke test)
- research 계층 추가 보강 (필요시)
