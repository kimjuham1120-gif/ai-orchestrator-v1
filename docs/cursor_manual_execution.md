# Cursor Execution — 자동/수동 실행 가이드 (Day 65~72 반영)

## 실행 모드

| 모드 | 설정 | 동작 |
|------|------|------|
| 수동 (기본) | `CURSOR_AUTO_MODE=false` | 기존 CLI 흐름 유지 |
| 자동 | `CURSOR_AUTO_MODE=true` | Cursor API 자동 호출 |

---

## 자동 모드 설정

`.env`에 추가:

```env
CURSOR_AUTO_MODE=true
CURSOR_API_KEY=cursor-...
CURSOR_REPO_PATH=C:\Users\...\ai-orchestrator-v1   # 실행할 저장소 경로
CURSOR_EXECUTION_TIMEOUT=600.0                      # 최대 대기 초
CURSOR_POLL_INTERVAL=10.0                           # polling 간격
```

자동 모드 흐름:
```
approve → packet 생성 → Cursor API 자동 호출
       → polling 완료 대기
       → execution_result 자동 저장
       → verification → finalize
```

자동 실패 시 → 수동 입력으로 자동 전환.

---

## 수동 모드 (기본 / fallback)

```env
CURSOR_AUTO_MODE=false   # 기본값, 설정 불필요
```

```
패킷 생성: True
패킷 경로: ./packet_run-abc123.md
위 파일을 Cursor Background Agent에 붙여넣고 실행하세요.

changed_files (쉼표 구분): src/auth.py, tests/test_auth.py
test_results: 5 passed
run_log: validate_token null 체크 추가로 로그인 버그 수정 완료
```

---

## execution_result 필드 규칙 (수동 모드)

| 필드 | 필수 | 올바른 예 | 실패 조건 |
|------|------|-----------|-----------|
| `changed_files` | ✅ | `src/auth.py` | 비어있음 → slice_issue |
| `test_results` | ✅ | `5 passed` | 비어있거나 `failed` 포함 |
| `run_log` | ✅ | `버그 수정 완료` | 비어있음 → slice_issue |

---

## 패킷 파일 구조 (변경 없음)

8개 필드: `run_id` / `goal` / `scope` / `target_files` /
`forbidden_actions` / `completion_criteria` / `test_command` / `output_format`
