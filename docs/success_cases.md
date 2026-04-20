# 성공 사례 문서 — ai-orchestrator-v1

Day 36~38 실제 CLI 실행 기록.

---

## 사례 1 — 일반 버그 수정 완주 (Day 36)

**요청:** `로그인 버그 수정해줘`

| 항목 | 값 |
|------|-----|
| task_type | code_fix |
| run_id | run-207f32b7 |
| research claims | 8개 (Gemini googleSearch) |
| plan steps | 9단계 |
| canonical_frozen | True |
| approval | approve |
| packet | `cursor_jobs/run-207f32b7.md` |
| changed_files | `src/auth.py` |
| test_results | `3 passed` |
| run_log | `로그인 버그 수정 완료` |
| final_status | **completed** |

**흐름 요약:**
```
요청 입력
→ Gemini research (8 claims)
→ cross_audit → canonical_freeze (frozen=True)
→ 9단계 실행 계획
→ approve → packet 생성
→ 결과 입력 → 검증 통과
→ completed
```

---

## 사례 2 — slice_issue 실패 유발 (Day 37)

**목적:** `changed_files=[]` 입력 시 slice_issue 분류 확인

| 항목 | 값 |
|------|-----|
| run_id | run-a4030431 |
| changed_files | `[]` (의도적 빈값) |
| test_results | `3 passed` |
| run_log | `수정 완료` |
| failure_type | **slice_issue** |
| all_passed | False |

**결론:** `changed_files` 비어있으면 반드시 `slice_issue` 분류됨.

---

## 사례 3 — doc_issue 실패 유발 (Day 38)

**목적:** scope 이탈 파일 입력 시 doc_issue 분류 확인

| 항목 | 값 |
|------|-----|
| run_id | run-a4030431 |
| target_files | `['src/auth.py']` |
| changed_files | `['src/unrelated.py']` (범위 이탈) |
| test_results | `3 passed` |
| run_log | `수정 완료` |
| failure_type | **doc_issue** |
| all_passed | False |

**결론:** `changed_files`가 `target_files` 범위 밖이면 `doc_issue` 분류됨.
`reaudit_doc()`으로 `target_files` 교정 후 재완주 가능.

---

## 공통 패턴

```
정상 완주 조건:
  changed_files: 1개 이상, target_files 범위 내
  test_results: 'passed' 포함, 'failed' 없음
  run_log: 비어있지 않음

실패 유발 조건:
  changed_files 비어있음     → slice_issue
  test_results 비어있음      → slice_issue
  run_log 비어있음           → slice_issue
  changed_files 범위 이탈    → doc_issue
```
