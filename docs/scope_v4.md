# scope.md v4 — ai-orchestrator 7-Phase 워크플로우 (Day 113~)

이 문서는 v4 범위를 **확정 고정**합니다. 구현 중 의문이 생기면 이 문서로 돌아와 확인하세요.

작성일: Day 113 진입 시점
전제: v3까지(411 passed)의 모든 구현이 baseline으로 존재.
      v4는 다이어그램 구현을 1순위로 하여 기존 제약을 공식 해제.

---

## 1. v4 원칙 전환

| 이전 원칙 (v1~v3) | v4 원칙 | 근거 |
|------------------|---------|------|
| artifact_store 스키마 불변 | **필요시 확장 허용** | 7-Phase 구현에 새 필드 불가피 |
| orchestrator/graph_flow 전면 수정 금지 | **필요한 만큼 수정 허용** | Phase별 재배치 필요 |
| 2-track 완전 분리 | **Phase 6에서 연결 (브릿지)** | 정보취득→앱개발 연결이 핵심 비전 |
| silent fallback 전면 금지 | **병렬 경로는 partial 허용** | 서브주제 × 어댑터 조합에서 현실적 필요 |
| 기존 구조 리팩터링 금지 | **Phase 단위 재구성 허용** | 다이어그램 구현 우선 |

### 불변 원칙 (v4에서도 유지)

- **단일 호출 경로의 silent fallback 금지** — key 있음 + 실패 → 예외 전파
- **stub/real 구분 엄격** — key 없으면 비활성, 속이지 않음
- **artifact_store SSOT** — 모든 상태는 DB 한 곳에만
- **Cursor = Executor 고정** — 파일 변경/git은 Cursor만

---

## 2. 7-Phase + Phase 0.5 전체 정의

### Phase 0.5 · 처리 가능성 게이트 (신규)

**역할**: 사용자 입력이 시스템 범위 안인지 판정 후 분기

**입력**: `raw_input: str`
**출력**: `{verdict, reason, suggested_clarification}`
- `verdict`: `"possible"` | `"out_of_scope"` | `"ambiguous"`

**판정 기준**

| 판정 | 조건 | 후속 |
|------|------|------|
| possible | 문서/앱 산출물로 풀 수 있음 | Phase 1로 |
| out_of_scope | 실시간 정보/물리세계/이미지 생성/법률·의료 자문 등 | 정중한 거절 + 이유 |
| ambiguous | 목표 불명확 ("뭐 시켜줘" 류) | 사용자에게 되물음 |

**구현**: LLM 1회 호출 (OpenRouter, 가벼운 모델). 판정 프롬프트는 예시 리스트 포함.

**파일**: `src/phases/phase_0_5_gate.py`

---

### Phase 1 · 서브주제 분해

**역할**: 큰 요청을 리서치 가능한 탐색 단위로 쪼개기

**입력**: `raw_input: str`, `feasibility: dict` (Phase 0.5 결과)
**출력**: `subtopics: list[str]` (5~8개)

**예시**
```
"사업계획서 써줘"
  ↓
["작성 방법론", "시장 규모", "경쟁사 분석 프레임워크",
 "차별화 포인트", "수익 모델", "재무 계획 템플릿"]
```

**구현**: OpenRouter 1회 호출 + JSON 파싱. 프롬프트에 "5~8개", "독립 조사 가능", "합치면 전체 커버" 명시.

**파일**: `src/phases/phase_1_decompose.py`

---

### Phase 2 · 병렬 리서치

**역할**: 각 서브주제를 3개 리서치 어댑터로 조사

**정책: subtopic 순차 + adapter 병렬** (결정사항 #2 B)
- 서브주제는 한 번에 하나씩
- 그 서브주제 내부에서 3개 어댑터(Gemini Deep, GPT Deep, Perplexity)는 동시 실행
- 이유: API 쿼터 보호 + 적당한 속도

**실패 정책 (partial 허용)**
```
key 없음           → 해당 어댑터 건너뜀 (기존 규칙 유지)
(subtopic, adapter) 실패 → 해당 쌍만 기록, 나머지 계속
특정 subtopic 전체 실패 → 해당 subtopic 제외하고 계속
모든 subtopic 실패 → 전체 예외 전파 (여기서만 silent fallback 금지 유지)
```

**출력 예시** (`parallel_research`)
```json
{
  "작성 방법론": {
    "gemini": {"claims": [...], "status": "success"},
    "gpt": {"claims": [...], "status": "success"},
    "perplexity": {"claims": [...], "status": "success"}
  },
  "시장 규모": {
    "gemini": {"claims": [...], "status": "success"},
    "gpt": {"status": "failed", "error": "timeout"},
    "perplexity": {"claims": [...], "status": "success"}
  }
}
```

**파일**: `src/research/parallel_router.py`

---

### Phase 3 · 2문서 합성

**역할**: 리서치 결과로 2개 문서를 **독립적으로** 생성

**Phase 3a · 기반정보 문서 (base_info_doc)**
- 리서치 결과만 정리
- 사용자 요청 맥락 무시
- 범용 참조 문서
- 예: "사업계획서 작성 방법론과 시장 조사 데이터 정리본"

**Phase 3b · 목표 산출물 초안 (target_doc)**
- 사용자의 원본 요청에 맞춤
- 리서치를 근거로 사용
- 실제 납품 문서
- 예: "우리 앱의 사업계획서 초안"

**구현**: OpenRouter 2회 호출 (3a, 3b 독립). 각각 다른 프롬프트 템플릿.

**파일**: `src/phases/phase_3_synthesize.py`

---

### Phase 4 · AI 교차 감사

**역할**: 3명의 감사관이 고유 정체성으로 문서를 감사하고 고도화

**기본값: ON + OFF 옵션 + 비용 경고** (결정사항 #3 C)
- 기본 활성화 (품질 우선)
- 사용자가 끌 수 있음
- CLI/UI에서 "Phase 4 실행 시 LLM 호출 4회 추가 (비용 약 3-4배)" 경고 표시

**3인 감사관 정체성 (확정)**

#### 구조 감사관 — Claude
> 차갑게 구조를 부수고 다시 세우는 감사관

- **담당**: 논리 비약, 구조 붕괴, 문단 순서, 빠진 전제, 결론 연결, 요구사항 누락
- **질문**: 논리 구조에 허점이 있는가 / 전제가 빠진 곳은 어디인가 / 문단 순서가 설득 흐름에 맞는가 / 무엇이 모호해서 실행 불가능한가
- **산출**: 구조상 치명적 문제 3개 / 누락된 전제 / 재구성 제안 / 문서 뼈대 수정안

#### 균형 감사관 — GPT
> 한쪽으로 기운 문서를 중립으로 되돌리는 감사관

- **담당**: 편향, 과장, 일방적 주장, 독자 관점 부족, 상대 입장 미반영, 설명의 공정성
- **질문**: 특정 관점으로 치우쳤는가 / 반론 가능성을 충분히 고려했는가 / 독자·심사자·사용자 입장에서 불편한 지점은 무엇인가 / 설득은 되지만 공정하지 않은 부분은 어디인가
- **산출**: 편향 포인트 / 과장 표현 / 반대 관점 보완 / 균형 수정안

#### 사실 감사관 — Gemini
> 현실과 최신 정보를 기준으로 사실을 검수하는 감사관

- **담당**: 사실성, 최신성, 외부 환경 반영, 수치/시장/정책/기술 정보 검증, 현실 적합성
- **질문**: 지금 기준으로 틀리거나 낡은 내용이 있는가 / 최신 시장·기술·정책과 어긋나는가 / 사실 근거가 약한 문장은 무엇인가 / 현실에서 바로 반박될 포인트는 무엇인가
- **산출**: 사실 오류 / 최신성 부족 / 검증 필요 문장 / 현실 기준 보정안

**통합 단계**
- 별도 LLM 호출 (Claude, 통합 역할)
- 3개 감사 결과를 받아 고도화 문서 생성
- 통합 규칙: 같은 지적 병합 / 상충 지적은 균형점 / 원본 좋은 부분 유지

**저장 형식** (`cross_audit_v4` 필드)
```json
{
  "round": 1,
  "document_before": "...",
  "audits": {
    "structure": {"role": "구조 감사관", "feedback": "..."},
    "balance":   {"role": "균형 감사관", "feedback": "..."},
    "fact":      {"role": "사실 감사관", "feedback": "..."}
  },
  "document_after": "...",
  "timestamp": "..."
}
```

**비용**: 1회 Phase 4 = LLM 4회 호출 (감사 3 + 통합 1)

**환경변수 추가**
```
AUDITOR_STRUCTURE_MODEL=anthropic/claude-sonnet-4.6
AUDITOR_BALANCE_MODEL=openai/gpt-5.4
AUDITOR_FACT_MODEL=google/gemini-2.5-pro
AUDITOR_SYNTHESIZER_MODEL=anthropic/claude-sonnet-4.6
PHASE_4_ENABLED=true
```

**파일**: `src/reviewer/cross_auditor.py`

---

### Phase 5 · 사용자 검수 루프

**역할**: 사용자 피드백을 받아 문서를 재작성하고 버전 관리

**버전 정책** (결정사항 #4 C)
- 저장: **무제한** (DB 용량 문제 없음)
- UI 표시: **최근 10개** + "더 보기" 버튼

**흐름**
```
v1 제시 → 사용자 피드백 → 재작성 → v2 제시 → 피드백 → ... → 만족 → 확정
```

**저장 형식** (`doc_versions` 필드)
```json
[
  {
    "version": 1,
    "document_type": "target_doc",
    "document": "...",
    "feedback_applied": null,
    "created_at": "..."
  },
  {
    "version": 2,
    "document_type": "target_doc",
    "document": "...",
    "feedback_applied": "재무 계획 더 구체적으로",
    "created_at": "..."
  }
]
```

**재작성 트리거**
- 단순 피드백 → Phase 3 재실행 (합성만 다시)
- "리서치 다시" 피드백 → Phase 2 재실행 (리서치부터 다시)
- "교차 감사 다시" → Phase 4 재실행 (감사만 다시)

**파일**: `src/phases/phase_5_feedback.py`, `src/document/version_manager.py`

---

### Phase 6 · 트랙 전환 결정

**역할**: 사용자가 "문서 완료" vs "앱개발 진입" 선택

**흐름**
```
Phase 5에서 문서 확정
  ↓
Phase 6 · 사용자에게 선택지 제시
  ├─ "문서 완료" → 최종 문서 반환, 프로젝트 종료
  └─ "앱개발" → target_doc을 deliverable_spec으로 변환 → Phase 7 진입
```

**변환 로직**
```python
def convert_doc_to_spec(target_doc: str) -> dict:
    """
    확정 문서를 Phase 7이 사용할 Final Deliverable Spec 형식으로.
    - target_files 추출 (LLM 판단)
    - success_criteria 추출
    - scope_boundary 추출
    """
```

**저장**: `bridge_decision` 필드에 `"doc_complete"` | `"app_dev"`

**파일**: `src/phases/phase_6_bridge.py`

---

### Phase 7 · 앱개발 실행

**역할**: Claude = Builder, Cursor = Executor

**7a · Claude Builder (기존 로직 재활용)**
- planner → builder → review
- 현재 graph_flow.py의 로직을 Phase 7 서브그래프로 감쌈
- 수정 최소화

**7b · Cursor Executor (기존 로직 재활용)**
- approval gate → execution packet → Cursor 수동 실행 → result_verifier → spec_alignment

**파일**: `src/phases/phase_7_app_dev.py` (기존 orchestrator.py 로직을 호출)

---

## 3. artifact_store 스키마 확장

### 기존 테이블 (유지)
기존 컬럼 전부 유지: `run_id`, `thread_id`, `raw_input`, `task_type`, `research_bundle`, `initial_document`, `cross_audit_result`, `canonical_doc`, `deliverable_spec`, `plan`, `builder_output` 등.

### v4 추가 컬럼 (artifacts 테이블)
```sql
project_id           TEXT              -- FK to projects.project_id
phase                TEXT              -- "phase_0_5_gate" ~ "phase_7b_execute"

-- Phase 0.5
feasibility_result   TEXT (JSON)

-- Phase 1
subtopics            TEXT (JSON)

-- Phase 2
parallel_research    TEXT (JSON)

-- Phase 3
base_info_doc        TEXT (JSON)
target_doc           TEXT (JSON)

-- Phase 4
cross_audit_v4       TEXT (JSON)

-- Phase 5
doc_versions         TEXT (JSON)
feedback_history     TEXT (JSON)

-- Phase 6
bridge_decision      TEXT
```

### 새 테이블: projects
```sql
CREATE TABLE IF NOT EXISTS projects (
    project_id      TEXT PRIMARY KEY,
    title           TEXT,
    raw_input       TEXT,
    created_at      TEXT,
    updated_at      TEXT,
    current_phase   TEXT,
    status          TEXT
);
```

### project_id ↔ run_id 관계 (결정사항 #1 B)

**1 프로젝트 = N run** (Phase마다 run_id 하나씩)

```
project_id: proj-abc123
  ├─ run-001 (phase_0_5_gate)
  ├─ run-002 (phase_1_decompose)
  ├─ run-003 (phase_2_research)
  ├─ run-004 (phase_3_synthesize)
  ├─ run-005 (phase_4_audit)
  ├─ run-006 (phase_5_feedback, v1)
  ├─ run-007 (phase_5_feedback, v2)
  ├─ run-008 (phase_6_bridge)
  └─ run-009~ (phase_7_app_dev)
```

각 run은 `project_id` 공유. Phase 재실행 시 새 `run_id` 발급.

---

## 4. graph_flow / orchestrator 재설계

### graph_flow.py — Phase별 서브그래프

```python
def build_phase_0_5_graph()
def build_phase_1_graph()
def build_phase_2_graph()
def build_phase_3_graph()
def build_phase_4_graph()
def build_phase_5_graph()
def build_phase_6_graph()
def build_phase_7_graph()
def build_master_graph()
```

### orchestrator.py — ProjectOrchestrator

```python
class ProjectOrchestrator:
    def start_project(raw_input: str) -> str
    def run_phase_0_5_gate(project_id) -> dict
    def run_phase_1_decompose(project_id) -> list[str]
    def run_phase_2_parallel_research(project_id) -> dict
    def run_phase_3_synthesize(project_id) -> tuple[dict, dict]
    def run_phase_4_cross_audit(project_id) -> dict
    def run_phase_5_apply_feedback(project_id, feedback: str) -> int
    def run_phase_6_bridge_decision(project_id, choice: str) -> str
    def run_phase_7_app_dev(project_id) -> str
    def resume_project(project_id) -> dict
```

### resume 정책 (결정사항 #5 B) — 프로젝트 단위

```python
def resume_project(project_id):
    proj = load_project(project_id)
    current = proj["current_phase"]
    return dispatch_to_phase(project_id, current)
```

---

## 5. 삭제 대상 (v3 잔재)

| 파일 또는 기능 | 이유 |
|---------------|------|
| `src/interpreter/lane_selector.py` | Phase 0.5 + Phase 6가 대체 |
| `src/interpreter/flow_router.py` | Phase 6가 대체 |
| `src/interpreter/request_interpreter.py` | Phase 0.5 + Phase 1이 대체 |
| `src/chat/info_retrieval_service.py` | Phase 1~5가 대체 |
| `src/chat/research_document_service.py` | Phase 2~3이 대체 |
| `src/research/youtube_adapter.py` | Deep Research 3종으로 충분 |
| `force_lane` 파라미터 | 테스트 잔재 |
| `use_interpreter=False` 옵션 | Phase 0.5 항상 거침 |
| `doc_only` 단독 모드 | Phase 5까지 가야 의미 있음 |
| `test_day105_3lane.py` | 2-track → Phase 구조로 폐기 |

---

## 6. 구현 순서

| Step | 작업 | 의존성 |
|------|------|--------|
| 1 | scope.md v4 선언 (이 문서) | 없음 |
| 2 | DB 스키마 확장 (projects 테이블 + artifacts 컬럼) | Step 1 |
| 3 | Phase 0.5 (처리 가능성 게이트) 구현 | Step 2 |
| 4 | Phase 1 (서브주제 분해) 구현 | Step 3 |
| 5 | Phase 2 (병렬 리서치 + partial 정책) 구현 | Step 4 |
| 6 | Phase 3 (2문서 분리) 구현 | Step 5 |
| 7 | Phase 6 (트랙 전환) 구현 + lane_selector/flow_router 제거 | Step 6 |
| 8 | Phase 5 (피드백 루프 + 버전 이력) 구현 | Step 6 |
| 9 | Phase 4 (AI 교차 감사) 구현 | Step 8 |
| 10 | Phase 7 재배치 | Step 7 |
| 11 | 웹 UI 재작성 | Step 10 |
| 12 | 레거시 코드 제거 + 테스트 재작성 | Step 11 |

**이유**:
- Phase 0.5를 먼저 → 범위 밖 요청 차단이 먼저 되어야 Phase 1이 안전
- Phase 6을 Phase 7보다 먼저 → 진입 경로가 있어야 Phase 7이 호출됨
- Phase 4를 뒤로 → 비용 부담, 나머지 안정화 후 추가
- Phase 7을 맨 뒤 → 기존 로직 재활용이라 위험도 낮음

---

## 7. 예상 변경 규모

| 항목 | 규모 |
|------|------|
| 신규 파일 | 약 18개 |
| 수정 파일 | `artifact_store.py`, `graph_flow.py`, `orchestrator.py`, `cli.py`, `web/app.py`, `.env`, `.env.example` |
| 삭제 파일 | 약 9개 |
| 테스트 재작성 | 약 200개 (기존 411 중 절반은 Phase 7 내부라 유지) |
| 소요 감각 | Day 113~150 (약 37일 분량) |

---

## 8. 확정 결정사항 (변경 금지)

| # | 항목 | 확정 |
|---|------|------|
| 1 | project_id ↔ run_id | 1 프로젝트 = N run |
| 2 | Phase 2 병렬 정책 | subtopic 순차 + adapter 병렬 |
| 3 | Phase 4 기본값 | ON + OFF 옵션 + 비용 경고 |
| 4 | Phase 5 버전 상한 | 저장 무제한, UI 최근 10개 |
| 5 | resume 단위 | 프로젝트 단위 |
| 6 | Phase 0.5 | 명시적 추가 (신규 게이트) |
| 7 | Phase 4 감사관 3인 정체성 | 구조 / 균형 / 사실 |
| 8 | Claude 역할 | Builder (코드 설계·작성) |
| 9 | Cursor 역할 | Executor (파일 쓰기·git·테스트) |

---

## 9. 불변 원칙 (v4에서도 유지)

1. **단일 호출 경로 silent fallback 금지** — 병렬 경로만 partial 허용
2. **stub/real 구분 엄격** — key 없으면 비활성
3. **artifact_store SSOT** — 모든 상태는 DB 한 곳에만
4. **Cursor = Executor 고정** — 파일 변경은 Cursor만
5. **사용자 승인 필수 지점** — Phase 6 트랙 전환, Phase 7a→7b 사이
6. **실행 취소 불가능한 작업** — `git push`, 외부 API, 파일 삭제는 Cursor 수동 실행만

---

## 10. 범위 밖 명시 (Phase 0.5가 자동 거절)

- 실시간 정보 (날씨, 주가, 지금 뉴스)
- 물리 세계 조작 (주문, 예약, 택시)
- 외부 계정 연동 (이메일, 캘린더, SNS)
- 창작 예술 (작곡, 그림 생성, 음성 합성)
- 법률·의료·금융 자문 (답변은 하되 책임 자문은 아님)
- 실시간 대화 상대 (게임, 대화 친구)
- 목표 없는 요청 ("아무거나", "랜덤으로")

이 영역 확장은 v5 이후로 미룸.

---

## 11. 참조

- 다이어그램: `workflow_final.svg` (7-Phase 최종)
- 이전 구현: v3 baseline (411 passed, Day 112 종료)
- 비전 분석: `docs/vision_analysis.md`

---

**이 문서는 Day 113 시점에 확정됨.**
**이후 변경은 scope.md v4.1 같은 개정판을 만들어야 함.**
**§8 확정 결정사항은 구현 중 변경 금지.**
