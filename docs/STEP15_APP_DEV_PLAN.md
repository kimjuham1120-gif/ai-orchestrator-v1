# Step 15 — 점진적 앱개발 시스템 설계

> **핵심**: Phase 1~6에서 만든 문서 묶음을 기반으로, 한 기능씩 점진적으로 앱을 만들어가는 시스템.
> 운영자가 매 단계 웹 UI로 결과 확인 + 결정점에서 멈춤.

확정일: 2026-04-28
다음 참조: 실제 구현 시 이 문서를 기준으로 작업.

---

## 0. 핵심 개념 — "프로젝트 = 한 앱 (한 도메인)"

**프로젝트는 영구적인 컨텍스트 컨테이너**. 한 번 만들면 며칠/몇 주에 걸쳐 누적.

```
┌─ 프로젝트 A: 교회 광고 게시판 앱 ─────────────┐
│  referenced_context (영구 저장):                │
│    - CLAUDE_교회게시판.md                       │
│    - feature_implementation.md                 │
│    - 교회_요구사항.md                            │
│  Todo 진행: 5/8 완료                             │
│  최근 빌드: 게시글 작성 폼 [completed]           │
│  preview 포트: 8001                             │
└────────────────────────────────────────────────┘

┌─ 프로젝트 B: RoomCrafting v1 ─────────────────┐
│  referenced_context (영구 저장):                │
│    - CLAUDE.md                                 │
│    - feature_implementation.md                 │
│    - code_fix.md                               │
│    - 00~07 기획문서 (8개)                       │
│    - 사업계획서.docx                             │
│    - sonnet_handoff_v5_4_final.md               │
│  Todo 진행: 2/12 완료                            │
│  최근 빌드: Vite 셋업 [completed]                │
│  preview 포트: 8002                             │
└────────────────────────────────────────────────┘

┌─ 프로젝트 C: 다른 앱... ─────────────────────┐
│  ...                                           │
└────────────────────────────────────────────────┘
```

### 의미하는 것
1. **프로젝트는 영구적** — 한 번 시작하면 끝날 때까지 유지 (며칠/몇 주)
2. **컨텍스트는 학습됨** — 매 Todo마다 LLM에게 "이 프로젝트의 기획서 묶음" 자동 전달
3. **여러 프로젝트 동시 진행 가능** — 교회 게시판 작업하다 RoomCrafting 작업하고 돌아옴
4. **재방문 시 즉시 컨텍스트 복원** — 프로젝트 클릭 → 어디까지 했는지 + 다음 Todo 보임
5. **각 프로젝트마다 별도 preview 포트** — 8001, 8002, 8003... 동시에 띄워도 충돌 없음

### 기존 시스템과의 통합

현재 ai-orchestrator-v1은 이미 `/projects`, `/project/{pid}` 라우트가 있음.
프로젝트 타입만 추가:

```
project_type:
  - "doc_generation"  (현재 기본 — 보고서/사업계획서 등 단일 문서)
  - "app_dev"         (새로 추가 — 점진적 앱 빌드)

app_dev 타입은:
  /project/{pid}/app-dev/dashboard   ← Todo 진행 상황
  /project/{pid}/app-dev/todos       ← Todo 목록
  /project/{pid}/app-dev/build       ← 현재 빌드 중
  /project/{pid}/app-dev/preview     ← 만들어진 앱 미리보기
```

### 사용자 흐름 (재방문 시나리오)

```
[프로젝트 리스트 페이지]
┌─────────────────────────────────────────────────┐
│ 새 프로젝트 만들기                                │
│   ○ 문서 생성 (보고서, 사업계획서 등)              │
│   ○ 앱개발 (점진적 빌드)  ← 새 옵션                │
│                                                  │
│ 진행 중인 프로젝트:                                │
│   📄 AI 시대 사업계획서       [완료]              │
│   🔧 교회 광고 게시판 앱      [진행 중 5/8]       │
│   🔧 RoomCrafting v1         [진행 중 2/12]      │
└──────────────────────────────────────────────────┘

[프로젝트 클릭]
  → 그 프로젝트의 referenced_context 자동 로드
  → 마지막 작업 지점에서 이어가기
  → "다음 Todo 시작" 또는 "현재 빌드 결과 확인"
```

---

## 1. 사용자 의도 (확정)

**시나리오**:
```
1. 새 앱개발 프로젝트 생성
   → 사용자가 [기획문서 묶음]을 업로드
     - CLAUDE.md (실행 규칙)
     - feature_implementation.md (한 기능 단위)
     - code_fix.md (버그 수정 단위)
     - 00~07 기획 문서
     - 사업계획서, 엑셀 등
   → 시스템이 프로젝트에 영구 저장 (referenced 컨텍스트)

2. 점진적 빌드 시작
   → LLM이 전체를 보고 TodoList 생성 (N개 기능 단위)
   → 운영자가 TodoList 검토 / 수정 / 승인

3. 한 단위씩 실행 (루프)
   → planner: "이번 단위에 무엇 만들까" (계획)
   → builder (Claude): 실제 코드 작성
   → executor (Cursor): 코드 적용 + 테스트
   → preview: 별도 포트로 앱 띄우기
   → 사용자: 웹 UI에서 확인
   → 결정: OK / 수정 요청 / 건너뛰기 / 중단

4. 완료까지 반복
```

---

## 2. 4가지 기준 결정사항

### (a) "기능 단위"의 정의

**원칙**: 사용자가 UI로 즉시 확인 가능한 단위.

**구체 기준**:
- ✅ 하나의 화면 (예: "방 입력 화면")
- ✅ 하나의 핵심 동작 (예: "가구 회전 기능")
- ✅ 하나의 엔진 함수 (예: "통로 판정")
- ❌ 너무 작음 (예: "한 줄 변경")
- ❌ 너무 큼 (예: "전체 UI")

**검증 기준**: 운영자가 UI에서 30초 안에 동작 확인 가능한 크기.

### (b) 결정점 — 정해진 룰 기반 (B)

**LLM에게 맡기지 않음**. 다음 사전 정의된 결정점에서만 멈춤:

| 결정점 | 사용자가 결정할 것 |
|---|---|
| 작업 단위 분해 후 | TodoList 검토/수정/승인 |
| 새 의존성 추가 | npm 패키지 설치 승인 |
| DB 스키마 변경 | 마이그레이션 승인 |
| 외부 API 호출 추가 | 어떤 서비스 / 비용 영향 |
| 새 화면 추가 | 라우트, 디자인 톤 |
| 인간 승인 필요 항목 | 판정 기준값, 비용 정책 등 (사용자 문서에 명시된 것) |
| 빌드/테스트 실패 | 재시도 / 우회 / 중단 |
| 한 작업 단위 완료 후 | OK / 수정 / 건너뜀 / 중단 |

**나머지는 자동 진행**.

### (c) 실행 + 확인 — 분업

```
Claude (이 시스템)        역할
  ├─ planner               계획 작성
  ├─ builder               코드 생성 (diff)
  └─ orchestrator          전체 흐름

Cursor                    역할 (운영자가 직접)
  ├─ 코드 적용 (apply patch)
  └─ 테스트 실행 (npm test, lint)

별도 포트 (예: 8001)       역할
  └─ 만들어진 앱 미리보기

운영자 (브라우저)          역할
  ├─ 우리 시스템 (8000): 진행 상황 확인 + 결정
  └─ 만든 앱 (8001):      실제 동작 확인
```

### (d) 기존 v3 인프라 활용

**Phase 7 영역을 점진적 모드로 변형**:

```
기존 Phase 7:  한 번에 planner→builder→review→approval→packet→execution→verification→finalize
                                                                ↓
새 Step 15:    각 작업 단위마다 위 사이클을 돌림 (반복)
```

기존 함수 재사용:
- `run_planner()` — 작업 단위 안의 세부 계획
- `run_builder()` — 코드 생성
- `run_review_gate()` — 리뷰
- `build_execution_packet()` — Cursor에 던질 패킷
- `update_execution_result()` — 결과 저장
- `verify_execution_result()` — 검증
- `finalize_run()` — 마무리

새로 만들 것:
- `todo_planner.py` — 전체 → N개 단위로 쪼개기
- `incremental_builder.py` — 한 단위씩 사이클 돌리는 래퍼

---

## 3. 데이터 모델

### 3.1 새 컬럼 (artifacts 테이블)

```sql
referenced_context  TEXT  -- JSON: 업로드된 기획문서 묶음
todo_list           TEXT  -- JSON: 작업 단위 목록
current_todo_idx    INTEGER  -- 현재 어느 단위 작업 중
todo_status         TEXT  -- "pending"|"in_progress"|"completed"|"failed"|"cancelled"
preview_port        INTEGER  -- 미리보기 포트 (8001 등)
```

### 3.2 referenced_context 구조

```json
{
  "files": [
    {
      "filename": "CLAUDE.md",
      "role": "execution_rules",
      "content": "...",
      "size_bytes": 12345
    },
    {
      "filename": "feature_implementation.md",
      "role": "feature_template",
      "content": "..."
    },
    {
      "filename": "00_제품한줄정의.md",
      "role": "spec",
      "content": "..."
    },
    ...
  ],
  "uploaded_at": "2026-04-28T..."
}
```

### 3.3 todo_list 구조

```json
{
  "items": [
    {
      "id": "todo-1",
      "title": "프로젝트 셋업 (Vite + React + TypeScript)",
      "description": "...",
      "type": "setup",
      "estimated_files": ["package.json", "vite.config.ts", "src/main.tsx"],
      "status": "completed",
      "result_run_id": "run-abc123"
    },
    {
      "id": "todo-2",
      "title": "방 입력 화면 (가로/세로/문/창문)",
      "description": "사용자가 방 크기와 문/창문 위치를 입력하는 화면. 직사각형만 허용.",
      "type": "feature",
      "estimated_files": ["src/components/RoomInput.tsx"],
      "status": "in_progress",
      "result_run_id": "run-def456"
    },
    {
      "id": "todo-3",
      "title": "Rule Engine — 통로 판정 함수",
      "description": "통로 폭 RED/ORANGE/GRAY/정상 판정. 기준: <45cm/45-59/60-79/≥80",
      "type": "engine",
      "estimated_files": ["src/engine/ruleEngine.ts"],
      "status": "pending"
    }
  ],
  "created_at": "...",
  "approved_at": "..."
}
```

### 3.4 작업 단위 타입

| type | 의미 |
|---|---|
| `setup` | 프로젝트 초기 셋업 (의존성, 설정) |
| `schema` | DB 스키마 / 타입 정의 |
| `engine` | 순수 로직 (Rule Engine, Cost Engine 등) |
| `feature` | UI + 동작 (사용자가 화면에서 확인 가능) |
| `integration` | 컴포넌트 연결 |
| `fix` | 버그 수정 |
| `refactor` | 리팩토링 (보통 점진 빌드에선 잘 안 함) |

---

## 4. 흐름 — 단계별 상세

### 4.1 프로젝트 생성 (한 번)

```
┌─ 웹 UI ─────────────────────────────────────────┐
│ "새 앱개발 프로젝트"                              │
│                                                   │
│ 요청 내용: [텍스트 입력]                           │
│ 기획문서 묶음 업로드 (다중 파일):                  │
│   [.md/.docx/.txt 파일 N개]                      │
│                                                   │
│ [프로젝트 시작]                                   │
└──────────────────────────────────────────────────┘
        ↓
Phase 0.5 (간단 — 앱개발 가능 여부 확인)
        ↓
referenced_context에 모든 파일 저장
        ↓
"Todo 생성하기" 버튼
```

### 4.2 TodoList 생성 (한 번)

```
LLM 호출:
  System: "당신은 점진적 앱개발 플래너다. 사용자의 기획 문서를 보고
           앱을 30~60분 단위로 N개 작업으로 분해하라.
           각 단위는 UI에서 즉시 확인 가능해야 한다."
  User:   [referenced_context 전체]
        ↓
Todo 7~15개 정도 생성
        ↓
운영자에게 표시 + 검토:
  ┌────────────────────────────────────┐
  │ 1. 프로젝트 셋업 (Vite+React)        [수정/삭제] │
  │ 2. Room 타입 정의                    [수정/삭제] │
  │ 3. 방 입력 화면                       [수정/삭제] │
  │ 4. Furniture 타입 + 가구 입력         [수정/삭제] │
  │ 5. 배치 캔버스 (drag/drop)            [수정/삭제] │
  │ 6. Rule Engine: 통로 판정             [수정/삭제] │
  │ 7. Rule Engine: 사용공간 판정         [수정/삭제] │
  │ 8. 경고 표시 UI                      [수정/삭제] │
  │ ...                                            │
  │                                                │
  │ [작업 추가] [순서 변경] [전체 승인]              │
  └────────────────────────────────────────────────┘
```

### 4.3 단위 빌드 루프 (반복)

```
[현재 작업: Todo #3 — 방 입력 화면]
        ↓
[a] Planner (Claude)
    → referenced_context + 현재 Todo + 이전 Todo 결과 보고
    → 세부 계획 작성
        ↓
[b] 결정점: 새 의존성? DB 변경? 외부 API?
    → 있으면 운영자에게 묻고 멈춤
        ↓
[c] Builder (Claude)
    → 실제 코드 생성 (diff 형식)
        ↓
[d] 운영자에게 표시:
    ┌──────────────────────────────────┐
    │ 📝 변경될 파일 (3개)               │
    │   + src/components/RoomInput.tsx │
    │   + src/types/room.ts            │
    │   ~ src/App.tsx                  │
    │                                   │
    │ [diff 보기 ▼] [전체 코드 ▼]        │
    │                                   │
    │ [Cursor로 적용] [수정 요청] [건너뛰기]│
    └────────────────────────────────────┘
        ↓
[e] 운영자가 [Cursor로 적용] 클릭
    → 패킷 다운로드 (Cursor에 던질 명령)
    → 운영자가 Cursor에 패킷 입력
    → Cursor가 코드 적용 + 테스트
        ↓
[f] 운영자가 결과 입력:
    "테스트 통과? Y/N"
    "에러 있음? 무엇?"
        ↓
[g] 결과에 따라:
    ✅ 통과 → preview 포트 (8001)에서 동작 확인
              → "OK / 수정 / 건너뜀" 결정
    ❌ 실패 → 재시도 / 디버깅 / 다음 단위로
        ↓
[h] 다음 Todo로 (또는 종료)
```

### 4.4 Preview Port

```
운영자 브라우저:
  Tab 1: http://localhost:8000  ← 우리 시스템 (Claude Orchestrator)
  Tab 2: http://localhost:8001  ← 만들어지고 있는 앱 (Vite dev server 등)

Tab 1에서 진행 상황 확인 + 결정
Tab 2에서 실제 동작 확인 (방 입력해보기, 가구 끌어보기 등)
```

---

## 5. 새로 만들 모듈

### 5.1 디렉토리 구조

```
src/
  app_dev/                              ← 새 모듈
    __init__.py
    todo_planner.py                     ← 전체 → N개 작업으로 분해
    incremental_builder.py              ← 한 단위씩 빌드 사이클
    decision_gate.py                    ← 결정점 검출 + 운영자 인터페이스
    preview_manager.py                  ← preview 포트 관리 (8001 등)
    context_uploader.py                 ← 기획문서 업로드/파싱

  web/
    templates/
      app_dev_create.html               ← 새 앱개발 프로젝트 (파일 다중 업로드)
      app_dev_dashboard.html            ← Todo 진행 상황
      app_dev_decision.html             ← 결정점 화면
      app_dev_diff.html                 ← 코드 diff 표시

    app.py                              ← 새 라우트 추가:
                                          /app-dev/new
                                          /app-dev/{pid}/todos
                                          /app-dev/{pid}/build/{todo_id}
                                          /app-dev/{pid}/decision
                                          /app-dev/{pid}/preview
```

### 5.2 todo_planner.py

```python
def generate_todo_list(
    raw_input: str,
    referenced_context: dict,  # 업로드된 파일들
    db_path: str,
) -> TodoListResult:
    """
    referenced_context를 LLM에 통째로 넣고
    "30~60분 단위로 분해하라" 지시.

    Returns: 7~15개 Todo 항목
    """
```

### 5.3 incremental_builder.py

```python
def build_one_todo(
    project_id: str,
    todo_id: str,
    db_path: str,
) -> BuildCycleResult:
    """
    한 Todo 항목에 대해 planner→builder→review→packet 사이클.

    출력: 운영자에게 보여줄 정보 (변경될 파일, diff 미리보기)
    상태: "ready_for_apply" (운영자가 Cursor로 적용할 준비됨)
    """
```

### 5.4 decision_gate.py

```python
def check_for_decisions_needed(
    plan: list[dict],
    builder_output: list[dict],
) -> list[Decision]:
    """
    plan과 builder_output을 보고 운영자 결정 필요한 항목 추출.

    예:
      - 새 의존성 (npm package)
      - DB 스키마 변경
      - 외부 API 호출
      - 인간 승인 필요 항목 (CLAUDE.md에 명시된 것)
    """
```

### 5.5 preview_manager.py

```python
def start_preview_server(
    project_id: str,
    code_dir: str,
    port: int = 8001,
) -> PreviewProcess:
    """
    만들어지고 있는 앱을 별도 포트에서 실행.

    실행 명령은 referenced_context의 CLAUDE.md 등에서 추론
    (또는 운영자가 직접 입력).
    예: "npm run dev" / "uvicorn app:app"
    """
```

---

## 6. 단계별 구현 우선순위

### Phase A — MVP (필수, 1~2 세션)
- [ ] referenced_context 컬럼 + 다중 파일 업로드
- [ ] todo_planner — 단순 LLM 호출로 N개 분해
- [ ] TodoList UI (검토/수정/승인)
- [ ] incremental_builder — 한 단위씩 planner→builder→packet
- [ ] 결정점 — 한 단위 완료 후 OK/수정/건너뜀만 (다른 결정점은 추후)
- [ ] 코드 diff 표시 (단순)
- [ ] Cursor 패킷 다운로드 (.md 파일로 내보내기)
- [ ] 운영자 결과 입력 (테스트 통과 Y/N + 코멘트)

### Phase B — 안정화 (선택, 1~2 세션)
- [ ] preview_manager — 자동 포트 띄우기
- [ ] 결정점 다양화 (의존성/DB/API/인간 승인)
- [ ] diff UI 강화 (syntax highlighting)
- [ ] 자동 retry 로직

### Phase C — 고도화 (장기)
- [ ] 자동 테스트 실행 (Cursor 없이)
- [ ] 스크린샷 자동 비교
- [ ] AI가 결정점 자동 발견

---

## 7. 사용 사례 — RoomCrafting 예시

### 입력
```
요청: "RoomCrafting v1을 만들어줘. 첨부 문서 기준."

업로드 파일:
  - CLAUDE.md
  - feature_implementation.md
  - code_fix.md
  - 00_제품한줄정의.md
  - 01_v1범위정의.md
  - 02_핵심문제제품정의서.md
  - 03_에이전트역할정의.md
  - 04_시스템구조도_인터페이스계약.md
  - 05_스키마설계.md
  - 06_분석설계.md
  - 07_개발환경설계.md
  - 사업계획서.docx
  - sonnet_handoff_v5_4_final.md
```

### 시스템 동작
```
1. Phase 0.5: ✅ "앱개발 가능"
2. 모든 파일 → referenced_context 저장
3. todo_planner: 파일 전체 분석 → 12개 Todo 생성:
   1. 프로젝트 셋업 (Vite + React + TS)
   2. canonical world schema 타입 정의
   3. Room 타입 + 방 입력 화면
   4. Furniture 타입 + 가구 입력 화면
   5. 2D 캔버스 (배치/회전/철거)
   6. Rule Engine: 통로 판정
   7. Rule Engine: 사용공간 판정
   8. Rule Engine: 문 열림 판정
   9. Cost Engine
   10. 경고 표시 UI (3단계)
   11. 배치안 저장 + 비교
   12. 구매리스트 + 딥링크 + 클릭 추적

4. 운영자: "OK 진행"
5. Todo #1 시작:
   - planner: "Vite + React + TS + Tailwind 프로젝트 생성"
   - builder: package.json, vite.config.ts, ... 생성 코드
   - 운영자: diff 확인 → "Cursor로 적용"
   - Cursor: npm create vite@latest ... 실행
   - 운영자: "OK"
   - preview 포트 8001에서 빈 React 앱 보임
6. Todo #2 시작...
   ...
```

---

## 8. 확정사항 (변경 금지)

이 문서를 기준으로 구현 시작. 변경 시 사용자 승인 필요.

- [x] 기능 단위 = 하나의 화면 또는 하나의 핵심 동작
- [x] 결정점 = 사전 정의된 룰 기반 (LLM 자동 판단 X)
- [x] Claude(우리)는 코드 생성, Cursor는 적용/테스트
- [x] preview 포트 = 8001 (앱개발마다 자동 할당)
- [x] 기존 Phase 7 인프라 재사용 (planner/builder/packet)
- [x] referenced_context는 영구 저장 (1 프로젝트 = 1 묶음)
- [x] Phase A (MVP) 먼저 구현, B/C는 추후

---

## 9. 다음 작업 (실제 구현 시작 시)

```
1. referenced_context 컬럼 + 다중 파일 업로드 UI (~1시간)
2. todo_planner.py + LLM 호출 (~1시간)
3. TodoList UI (검토/수정/승인) (~1시간)
4. incremental_builder.py — Phase 7 재사용 (~1.5시간)
5. 결정점 1단계 (Todo 완료 후 OK/수정/건너뜀) (~1시간)
6. Cursor 패킷 형식 정의 + 다운로드 (~30분)
7. 운영자 결과 입력 UI (~30분)
8. 통합 테스트 — 작은 예시 1개로 끝까지 돌려보기 (~1시간)

총: 약 7~8시간 (3~4 세션 분량)
```

---

*기준 문서: 사용자가 보낸 RoomCrafting 기획 묶음 + 현재 ai-orchestrator-v1 코드베이스*
*다음: Phase A 구현 시작 (todo_planner + UI 부터)*
