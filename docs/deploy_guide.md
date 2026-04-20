# 배포 가이드 — ai-orchestrator-v2

---

## 1. 배포 원칙

```
클로드 수정본 받음
→ 파일 덮어쓰기
→ pytest -v
→ smoke test
→ 이상 없으면 다음 작업
```

한 번에 전부 몰아서 하지 말고, 범위별로 배포 후 검증한다.

---

## 2. 배포 전 준비

```powershell
# Git 사용 시
git status
git add .
git commit -m "backup before next patch deploy"

# Git 미사용 시
# 프로젝트 폴더 전체 복사본 생성
```

- 현재 `.env` 백업
- 현재 동작하는 브랜치 확인
- 클로드가 준 파일 목록 정리

---

## 3. 파일 배포 방식

클로드가 준 파일은 지정 경로에 같은 이름으로 덮어쓰기.

| 액션 | 방법 |
|------|------|
| 없는 파일 | 새로 생성 |
| 기존 파일 | 덮어쓰기 |
| 삭제 대상 | 실제 삭제 |

```powershell
# 삭제 예시 (Windows)
del tests\test_day49_tavily_openrouter.py

# 삭제 예시 (macOS/Linux)
rm tests/test_day49_tavily_openrouter.py
```

---

## 4. .env 반영

클로드 수정본이 env 항목을 추가했으면 `.env`에 직접 반영.

```env
OPENROUTER_API_KEY=
OPENROUTER_PLANNER_MODEL=openai/gpt-5.4
OPENROUTER_BUILDER_MODEL=anthropic/claude-sonnet-4.6
OPENROUTER_DOC_MODEL=openai/gpt-5.4-mini
OPENROUTER_REVIEWER_MODEL=openai/gpt-5.4-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_PLANNER_REASONING_EFFORT=high
OPENROUTER_BUILDER_VERBOSITY=high

GEMINI_API_KEY=
GEMINI_DEEP_RESEARCH_AGENT=deep-research-pro-preview-12-2025
GEMINI_DEEP_RESEARCH_TIMEOUT=600.0
GEMINI_DEEP_RESEARCH_POLL_INTERVAL=10.0

OPENAI_API_KEY=
GPT_RESEARCH_MODEL=openai/o4-mini-deep-research
GPT_RESEARCH_TIMEOUT=120.0
GPT_RESEARCH_MAX_TOKENS=2000

PERPLEXITY_API_KEY=
YOUTUBE_TRANSCRIPT_MODE=manual

CURSOR_AUTO_MODE=false
CURSOR_API_KEY=
CURSOR_REPO_PATH=
CURSOR_EXECUTION_TIMEOUT=600.0
CURSOR_POLL_INTERVAL=10.0
```

**주의:** `.env.example`은 참고용. 실제 동작은 `.env` 기준.

---

## 5. 테스트 배포 검증

```powershell
.venv\Scripts\activate
pytest -v --timeout=30
```

확인 항목:
- passed 수
- failed 0개 여부
- import error 여부
- syntax error 여부

---

## 6. 스모크 테스트

### A. 리서치 스모크

```powershell
python -m src.cli
# 요청: "버그 수정해줘"
# waiting_approval 후 새 터미널에서 DB 확인
python -c "from dotenv import load_dotenv; load_dotenv(); from src.store.artifact_store import load_artifact; a = load_artifact('orchestrator_v1.db', run_id='<run_id>'); bundle = a.get('research_bundle', {}); claims = bundle.get('claims', []); print('총 claims:', len(claims)); [print(' ', c.get('source',''), c.get('text','')[:60]) for c in claims]"
```

확인: `gpt_research` / `gemini_deep_research` source 포함 여부

### B. 오케스트레이터 스모크

```powershell
python -m src.cli
# 새 요청 → approve → packet 생성 확인
```

### C. Cursor 자동화 스모크 (CURSOR_API_KEY 있을 때)

```env
CURSOR_AUTO_MODE=true
```

자동 실패 시 수동 입력으로 전환되는지 확인.

---

## 7. 이상 생기면

```
1) 파일 경로 잘못 덮어썼는지
2) 삭제 대상 파일 남아있는지
3) .env 누락인지
4) 테스트가 이전 기대값을 아직 쓰는지
```

롤백:

```powershell
git restore .          # 워킹 디렉토리 복원
git reset --hard HEAD  # 커밋 기준 복원
```

---

## 8. 배포 완료 판정

아래가 다 맞으면 해당 범위 배포 완료:

```
[ ] 파일 반영 완료
[ ] .env 반영 완료
[ ] pytest -v --timeout=30 통과
[ ] smoke test 성공
[ ] 문서 저장 완료
```

---

## 9. 권장 실행 순서

```
1. git commit (백업)
2. 파일 덮어쓰기 / 삭제
3. .env 반영
4. pytest -v --timeout=30
5. smoke test
6. 문제 없으면 다음 범위 진행
```

---

## 10. 중복 파일 확인 (Windows PowerShell)

```powershell
# .py 파일 중복 확인
Get-ChildItem -Path src, tests -Recurse -Filter "*.py" | Group-Object Name | Where-Object { $_.Count -gt 1 } | Select-Object Name, Count

# 특정 파일 위치 확인
Get-ChildItem -Path src -Recurse -Filter "router.py" | Select-Object FullName
```
