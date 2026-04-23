# Step 14 계획서 v2 — 최적화·고도화 (claw-code 패턴 통합)

> 이전 버전(v1): 3과제 (비용·병렬·SSE)
> 이번 버전(v2): **6과제** — claw-code 패턴 4개 중 유효한 것 통합 + 우선순위 재조정
> 전제: Step 13 종료 (pytest 403 passed) 이후 시작
> 추후 예정: Perplexity/Gemini/GPT 프로바이더별 토큰 절약 기법 → v3에 반영

---

## 착수 전 체크리스트

- [x] Step 13 완료 (403 passed 달성)
- [x] `git commit` Step 13 종료 태그 `v4.13-done`
- [x] origin push 완료 (secret scanning clean)
- [x] `.env` 자동 로드 (app.py load_dotenv)
- [ ] 현재 코스트 기준선 측정 (1회 전체 실행 시 토큰·시간 기록)
- [ ] 프로바이더별 토큰 절약 리서치 완료 (사용자 별도 작업)

---

## 전체 과제 맵 (6개)

| # | 과제 | 우선순위 | 영향 | 소요 | 근거 |
|---|---|---|---|---|---|
| 14-1 | **비용 추적 + 예산 상한** | **최상** | 운영 안전·사고 방지 | 2.5일 | 기존 + claw-code #3 |
| 14-2 | **JSON 응답 재시도** | 상 | LLM 파싱 실패 20~40% 감소 | 0.5일 | claw-code #4 |
| 14-3 | **Phase 5 피드백 압축** | 상 | 장기 루프 15~25% 토큰 감소 | 1일 | claw-code #2 |
| 14-4 | **Phase 2 병렬 확대** | 중 | 체감 속도 큰 개선 | 1.5일 | 기존 |
| 14-5 | Phase 체크포인트·재개 | 하 | 중단 시 복구 | 1일 | claw-code #1 |
| 14-6 | 웹 UI SSE | 하 | UX 개선 (polling 대체 가능) | 2일 | 기존 |

**합계: 8.5일** (+ 버퍼 2일 → 10.5일)

---

## 권장 실행 순서

```
① 14-1 비용 추적      → 기준선 확보 (모든 후속 개선 측정 기반)
② 14-2 JSON 재시도    → 빠른 승부 (0.5일, 즉시 효과)
③ 14-3 피드백 압축    → 토큰 절감 본격화
④ 14-4 Phase 2 병렬   → 속도 개선 (비용 추적으로 전후 비교)
⑤ 14-5 체크포인트     → 운영 안정성
⑥ 14-6 SSE            → UX (여유되면)
```

이유:
- **14-1 먼저** = 나머지 5개의 개선 효과를 **숫자로 증명**할 수 있음
- **14-2 두 번째** = 0.5일로 가장 큰 ROI (parsing 실패 재호출 비용 즉시 감소)
- **14-3, 14-4** = 본격 최적화
- **14-5, 14-6** = 있으면 좋은 것 (필수 아님)

---

## 과제 1 · 비용 추적 + 예산 상한 (최우선)

### 목표
모든 LLM 호출에 대해:
- 토큰 사용량 기록
- 캐시 히트율 추적
- **예산 상한 도달 시 자동 중단** (claw-code `max_budget_tokens` 패턴)

### 설계

#### 1-1. DB 스키마

```sql
CREATE TABLE IF NOT EXISTS llm_calls (
    call_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT,
    project_id    TEXT,
    phase         TEXT,
    model         TEXT,
    prompt_tokens INTEGER,
    output_tokens INTEGER,
    cached_tokens INTEGER,
    cost_usd      REAL,
    duration_ms   INTEGER,
    created_at    TEXT,
    error         TEXT
);
CREATE INDEX idx_llm_calls_run ON llm_calls(run_id);
CREATE INDEX idx_llm_calls_project ON llm_calls(project_id);
```

#### 1-2. 단가 테이블 (`src/utils/model_pricing.py` 신규)

```python
MODEL_PRICING = {
    "openai/gpt-5.4": {
        "input_per_1m": 2.50,
        "output_per_1m": 10.00,
        "cache_discount": 0.50,
    },
    "anthropic/claude-opus-4.7": {
        "input_per_1m": 15.00,
        "output_per_1m": 75.00,
        "cache_discount": 0.10,
    },
    "google/gemini-3.1-pro-preview": {
        "input_per_1m": 1.25,
        "output_per_1m": 5.00,
        "cache_discount": 1.00,
    },
    # Perplexity 등 리서치 완료 후 추가
}
```

#### 1-3. `call_llm` 시그니처 확장

```python
def call_llm(
    prompt: str,
    model: str,
    timeout: float,
    use_cache: bool = True,
    # 신규 (optional, 하위호환)
    run_id: Optional[str] = None,
    project_id: Optional[str] = None,
    phase: Optional[str] = None,
    db_path: Optional[str] = None,
    budget_guard: Optional["BudgetGuard"] = None,   # ← claw-code 패턴
) -> Optional[str]:
    # 예산 체크
    if budget_guard and budget_guard.exceeded():
        return None  # 조용히 실패 → Phase가 fallback 처리

    # ... 호출 ...

    # usage 파싱 & DB 기록 & 예산 차감
    if budget_guard:
        budget_guard.consume(cost_usd)
```

#### 1-4. BudgetGuard (`src/utils/budget_guard.py` 신규)

```python
@dataclass
class BudgetGuard:
    max_cost_usd: float = 5.00       # 프로젝트당 기본 상한
    max_tokens_total: int = 500_000  # 토큰 상한
    current_cost: float = 0.0
    current_tokens: int = 0

    def exceeded(self) -> bool:
        return (
            self.current_cost >= self.max_cost_usd
            or self.current_tokens >= self.max_tokens_total
        )

    def consume(self, cost: float, tokens: int = 0):
        self.current_cost += cost
        self.current_tokens += tokens
```

환경변수로 상한 조정 가능:
- `BUDGET_PROJECT_MAX_USD=5.0`
- `BUDGET_PROJECT_MAX_TOKENS=500000`

#### 1-5. 집계 API

```python
def get_run_cost(db_path, run_id) -> dict:
    """한 run의 총 비용 + Phase별 breakdown."""

def get_project_cost(db_path, project_id) -> dict:
    """프로젝트 전체 비용."""
```

#### 1-6. 웹 UI 표시
프로젝트 상세 페이지 상단에 **비용/토큰/캐시 히트율** 뱃지.

### 테스트 (`test_day125_cost_tracking.py`)
- LLM mock 응답에 usage 포함 → DB 기록 검증
- 모델별 비용 계산 정확성
- 캐시 할인 반영
- BudgetGuard 상한 도달 시 call_llm이 None 반환
- `db_path=None` 일 때 기록 없이 정상 동작 (하위호환)

### 예상 소요
- DB 스키마 + pricing + BudgetGuard: 1일
- llm_utils 확장 + 회귀 테스트: 1일
- 집계 API + UI 뱃지: 0.5일
- **합계 2.5일**

---

## 과제 2 · JSON 응답 재시도 (Quick Win)

### 근거: claw-code `_render_structured_output`

```python
for _ in range(self.config.structured_retry_limit):
    try:
        return json.dumps(payload, indent=2)
    except (TypeError, ValueError) as exc:
        last_error = exc
        # 재시도
```

### 목표
Phase 1(서브주제), Phase 4(감사관) 등이 **JSON 파싱 실패**로 Phase 전체 실패하는 현상 방지.

### 설계

`llm_utils.py`에 래퍼 함수 추가:

```python
def call_llm_json(
    prompt: str,
    model: str,
    timeout: float,
    schema: Optional[dict] = None,
    retry_limit: int = 2,
    **kwargs,
) -> Optional[dict]:
    """
    JSON 응답을 기대하는 호출. 파싱 실패 시 보정 프롬프트로 재시도.
    """
    original_prompt = prompt
    last_error = None

    for attempt in range(retry_limit + 1):
        text = call_llm(prompt, model, timeout, **kwargs)
        if text is None:
            return None

        # 마크다운 코드블록 제거
        text = _strip_json_fence(text)

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            last_error = e
            # 재시도 프롬프트 — LLM에게 오류 알리고 수정 요청
            prompt = (
                f"{original_prompt}\n\n"
                f"[이전 응답이 JSON 파싱 실패했습니다: {e}]\n"
                f"정확한 JSON만 출력하세요. 설명이나 코드블록 없이."
            )
            continue

    return None  # 최대 재시도 소진
```

### 적용 대상
- `phase_1_decompose.py` — 서브주제 JSON
- `phase_4_audit.py` — 감사관 결과 JSON
- `phase_6_bridge.py` — 트랙 결정 JSON
- (기타 `json.loads` 호출하는 곳 전부)

### 기대 효과
- 파싱 실패 재호출 비용 **20~40% 감소**
- Phase 실패율 감소 → 사용자 재시도 횟수 감소

### 테스트 (`test_day126_call_llm_json.py`)
- 첫 응답 JSON 깨짐 → 재시도로 복구
- 두 번 다 실패 → None 반환
- 성공 케이스 정상 파싱
- 마크다운 ```json 래퍼 자동 제거

### 예상 소요 **0.5일**

---

## 과제 3 · Phase 5 피드백 압축 (토큰 절감 핵심)

### 근거: claw-code `TranscriptStore.compact`

```python
def compact(self, keep_last: int = 10) -> None:
    if len(self.entries) > keep_last:
        self.entries[:] = self.entries[-keep_last:]
```

### 현재 문제
Phase 5 피드백 루프가 5회+ 돌면 **이전 버전 전부 + 피드백 전부**가 프롬프트에 쌓임. 버전 10개 × 평균 2000자 = 20,000자 → **토큰 폭증**.

### 목표
오래된 버전은 **요약으로 대체**, 최근 N개만 원문 유지.

### 설계

#### 3-1. 압축 정책 (`src/phases/phase_5_feedback.py` 수정)

```python
def _build_feedback_prompt(current_doc, feedback, history):
    recent = history[-3:]           # 최근 3개만 원문
    older = history[:-3]            # 나머지는 요약

    history_section = []
    if older:
        history_section.append(
            f"## 이전 버전 요약 ({len(older)}개)\n"
            f"{_summarize_older_versions(older)}"
        )
    for v in recent:
        history_section.append(
            f"## 버전 {v['version']}\n{v['document'][:1500]}..."
        )
```

#### 3-2. 요약 전략
- **방법 A (단순)**: 오래된 버전은 **피드백 내용만** 유지 → "v2: 톤 다듬기 요청, v3: 예시 추가 요청"
- **방법 B (LLM)**: 3개 넘어가면 LLM이 한 줄 요약 생성 → 캐시에 저장
- **권장**: 방법 A (비용 0, 구현 단순)

#### 3-3. 설정값

환경변수:
- `PHASE_5_KEEP_RECENT=3`
- `PHASE_5_DOC_TRUNCATE=1500`

### 기대 효과
- 피드백 5회차 기준 프롬프트 크기 **약 40% 감소**
- 실질 토큰 비용 **15~25% 절감**

### 테스트 확장 (`test_day119_phase_5.py`)
- 버전 10개 누적 시 프롬프트 길이 측정 → compact 전후 비교
- 최근 3개는 원문 유지 확인
- 오래된 버전은 요약 섹션에 들어감 확인

### 예상 소요 **1일**

---

## 과제 4 · Phase 2 병렬 확대

### 현재 상태
Phase 2는 서브주제 N개 × 어댑터 M개 = N×M 호출이 **순차 처리**.
5 × 3 = 15회 × 30초 = 7~8분.

### 목표
`asyncio.gather` + `httpx.AsyncClient` 로 **동시 실행** → 전체 소요 1/N.

### 설계

#### 4-1. `call_llm_async` 추가 (`llm_utils.py`)

```python
async def call_llm_async(
    prompt: str,
    model: str,
    timeout: float,
    use_cache: bool = True,
    **kwargs,
) -> Optional[str]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        # ... 동일 로직, async 버전 ...
```

sync `call_llm`은 유지 (다른 Phase에서 계속 사용).

#### 4-2. Phase 2 async 전환

```python
import asyncio

async def run_phase_2_async(subtopics, adapters, semaphore):
    async def one_call(subtopic, adapter):
        async with semaphore:
            return await adapter.run_async(subtopic)

    tasks = [
        one_call(s, a)
        for s in subtopics
        for a in adapters
    ]
    return await asyncio.gather(*tasks, return_exceptions=True)

def run_phase_2(subtopics, adapters):
    semaphore = asyncio.Semaphore(int(os.environ.get("PHASE_2_CONCURRENCY", "5")))
    return asyncio.run(run_phase_2_async(subtopics, adapters, semaphore))
```

#### 4-3. 동시성 제한
`PHASE_2_CONCURRENCY=5` (기본) — OpenRouter rate limit 고려.

### 리스크 & 대응
- **어댑터 async 미대응** → `asyncio.to_thread`로 sync 어댑터 래핑
- **rate limit 429** → llm_utils 재시도 정책에 429 포함 (현재는 4xx 재시도 없음 — 수정 필요)
- **예외 전파** → `return_exceptions=True`로 개별 실패 수용

### 테스트 (`test_day127_phase_2_parallel.py`)
- 3 서브주제 × 2 어댑터 = 6 호출 → 총 소요 < 단일 호출 × 1.5
- 1개 실패 → 나머지 완주
- Semaphore 동시성 제한 확인
- 기존 Phase 2 테스트 회귀 없음

### 예상 소요 **1.5일**

---

## 과제 5 · Phase 체크포인트·재개 (복구)

### 근거: claw-code `session_store.py`

### 목표
Phase 중간에 서버 재시작/크래시 발생해도 **이미 받은 결과는 보존**, 남은 것만 재실행.

### 현재 문제
Phase 2가 15개 호출 중 10개 완료 후 크래시 → 전체 재실행 → **10개 호출 비용 낭비**.

### 설계

#### 5-1. 중간 저장 정책
Phase 2 각 호출 완료 시 **즉시 DB에 append**.

```python
for subtopic, adapter, result in completed_calls:
    update_artifact_partial(db_path, run_id, {
        f"parallel_research.{subtopic}.{adapter}": result
    })
```

#### 5-2. 재개 로직

```python
def resume_phase_2(run_id):
    existing = load_partial_results(run_id)
    all_calls = enumerate_required_calls(run_id)
    todo = [c for c in all_calls if c.key not in existing]
    # todo만 실행
```

#### 5-3. Phase별 재개 지원 매트릭스
| Phase | 재개 난이도 | 우선순위 |
|---|---|---|
| Phase 2 | 쉬움 (호출 독립) | 높음 |
| Phase 3 | 중간 (3a/3b 독립) | 중간 |
| Phase 4 | 쉬움 (감사관 독립) | 높음 |
| Phase 5 | 어려움 (순차 의존) | 낮음 |

### 예상 소요 **1일** (Phase 2 + 4만)

---

## 과제 6 · 웹 UI SSE

기존 계획 그대로. 우선순위는 낮음.

### 대안
**5초 polling**으로 충분할 가능성 → SSE는 필수 아님.

### 예상 소요 **2일** (또는 polling으로 0.5일)

---

## 프로바이더별 토큰 절약 (추후 v3에 반영)

사용자가 리서치 완료 시 이 섹션에 통합 예정. 체크리스트:

### Perplexity
- 모델 선택: `sonar-small` / `sonar-pro` / `sonar-deep-research` 비용차
- `search_domain_filter` — 검색 범위 축소
- `search_recency_filter` — 오래된 문서 제외
- `return_citations=false` — citation 토큰 절감
- `max_tokens` 명시

### Gemini
- **Context Caching API** (75% 할인, 반복 프롬프트)
- `thinking_budget` (2.5 Flash)
- 모델: Flash vs Pro vs Deep (10배 가격차)
- **Batch API** (50% 할인)
- 이미지 해상도 다운샘플

### GPT (OpenAI)
- **Prompt Caching** (자동, 1024토큰↑, 50% 할인)
- **Batch API** (50% 할인)
- 모델: `gpt-5-nano` / `gpt-5-mini` / `gpt-5`
- **Structured Outputs** (파싱 실패 방지)
- `reasoning_effort: "minimal"` (o시리즈)

### 반영 방식
Step 14-1 `model_pricing.py`에 **프로바이더별 할인 규칙** 추가, `call_llm`이 자동 적용.

---

## Definition of Done

- [ ] pytest 전체 passing (예상 440+)
- [ ] 프로젝트 상세 페이지에 비용·토큰·캐시 히트율 표시
- [ ] Phase 2 소요시간 before/after 비교 수치
- [ ] BudgetGuard 동작 확인 (초과 시 자동 중단)
- [ ] Phase 5 피드백 루프 5회 이상 시 토큰 사용량 측정
- [ ] JSON 재시도 동작 로그 확인
- [ ] (선택) SSE 또는 polling으로 진행 상황 표시
- [ ] `README.md` · `project_context.md` 갱신

---

## Step 14 이후 후보 (기록만)

- 코드 경량화 (별도 문서 `step_14_refactor_plan.md` 예정)
- 배포 (Railway / Render, Basic Auth)
- 프로바이더별 할인 통합 (v3에서 반영)
- v5: 에이전트 자동 실행 (Cursor handoff 제거)

---

## 변경 이력

- **v1** (Day 123): 3과제 (비용·병렬·SSE)
- **v2** (현재): 6과제로 확장 — claw-code 패턴 4개 중 유효한 것(3개) 통합, JSON 재시도 최우선으로 재조정
- **v3** (예정): 프로바이더별 토큰 절약 반영 (사용자 리서치 결과 대기)
