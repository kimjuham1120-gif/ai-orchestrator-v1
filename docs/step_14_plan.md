# Step 14 계획서 — 남은 3과제

> 전제: Step 13 종료 (pytest 403 passed) 이후 시작
> 범위: Phase 2 병렬 확대 / 비용 추적 / 웹 UI SSE
> 제외: 배포·v5 비전은 별도 문서

---

## 착수 전 체크리스트

- [ ] Step 13 완료 (403 passed 달성)
- [ ] `git commit` Step 13 종료 태그 (예: `v4.13-done`)
- [ ] 현재 코스트 기준선 측정 (Phase 1회 전체 실행 시 토큰 사용량 기록)

---

## 과제 1 · Phase 2 병렬 확대

### 현재 상태
- Phase 2는 서브주제 N개를 **순차** 리서치 (추정)
- 1개 서브주제 평균 소요: 약 30~60초
- 서브주제 5개면 3~5분 대기

### 목표
서브주제를 동시에 리서치 → **전체 Phase 2 소요 1/N 수준으로 단축**

### 설계

#### 동시성 방식
`asyncio.gather` 사용. `httpx.AsyncClient` 로 전환.

```python
# src/utils/llm_utils.py 에 async 버전 추가
async def call_llm_async(
    prompt: str,
    model: str,
    timeout: float,
    use_cache: bool = True,
) -> Optional[str]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        ...
```

sync 버전 `call_llm`은 유지 (기존 Phase에서 계속 사용).

#### Phase 2 내부 변경

```python
# src/phases/phase_2_*.py
import asyncio

async def research_subtopic_async(subtopic, adapters):
    tasks = [adapter.run(subtopic) for adapter in adapters]
    return await asyncio.gather(*tasks, return_exceptions=True)

async def run_phase_2_async(subtopics, adapters):
    tasks = [research_subtopic_async(s, adapters) for s in subtopics]
    return await asyncio.gather(*tasks)

# 기존 sync 진입점 유지
def run_phase_2(subtopics, adapters):
    return asyncio.run(run_phase_2_async(subtopics, adapters))
```

#### 동시성 제한
전역 `asyncio.Semaphore(N)` 로 동시 요청 수 제한.
- 기본 N = 5 (OpenRouter 무료 티어 rate limit 고려)
- 환경변수 `PHASE_2_CONCURRENCY` 로 조정

### 리스크
- 어댑터가 모두 async 대응 필요 — sync 어댑터 있으면 `run_in_executor` 로 래핑
- 예외 하나가 전체를 죽이면 안 됨 → `return_exceptions=True` + 개별 실패 처리
- rate limit 초과 시 429 → llm_utils의 재시도가 받아야 함 (4xx 재시도 없음 정책 수정 필요할 수도)

### 테스트
- `tests/test_day124_phase_2_parallel.py` 신규
  - 3개 서브주제 동시 실행 → 총 소요 < 단일 소요 × 1.5
  - 1개 실패 → 나머지는 완주 확인
  - Semaphore 동시성 제한 동작 확인
- 기존 Phase 2 테스트는 그대로 passing 유지

### 예상 소요
- 구현: 0.5일
- 테스트: 0.5일
- 회귀 확인: 0.5일
- **합계 1.5일**

---

## 과제 2 · 비용 추적

### 목표
LLM 호출마다 입력·출력 토큰 수와 예상 비용을 DB에 기록 → 프로젝트별·Phase별 집계.

### 설계

#### 2-1. DB 스키마 추가

```sql
CREATE TABLE IF NOT EXISTS llm_calls (
    call_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT,
    project_id    TEXT,
    phase         TEXT,           -- "phase_3a", "phase_4_structure" 등
    model         TEXT,
    prompt_tokens INTEGER,
    output_tokens INTEGER,
    cache_hit     INTEGER,        -- 0/1
    cost_usd      REAL,
    duration_ms   INTEGER,
    created_at    TEXT,
    error         TEXT
);
CREATE INDEX idx_llm_calls_run ON llm_calls(run_id);
CREATE INDEX idx_llm_calls_project ON llm_calls(project_id);
```

`artifact_store.py`의 `_connect()` 에서 멱등하게 생성.

#### 2-2. llm_utils.call_llm 시그니처 확장

```python
def call_llm(
    prompt: str,
    model: str,
    timeout: float,
    use_cache: bool = True,
    # 신규 (optional, 하위호환 보장)
    run_id: Optional[str] = None,
    phase: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[str]:
    ...
    # OpenRouter 응답의 usage 필드 파싱
    usage = response.json().get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)
    cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)

    # DB 기록 (db_path 제공된 경우만)
    if db_path and run_id:
        _record_llm_call(
            db_path, run_id, phase, model,
            prompt_tokens, output_tokens, cached_tokens, ...
        )
```

호환성: `run_id/phase/db_path` 모두 optional → 기존 호출 그대로 동작.

#### 2-3. 비용 계산

모델별 단가 테이블 하드코딩 (별도 파일):

```python
# src/utils/model_pricing.py
MODEL_PRICING = {
    "openai/gpt-5.4": {
        "input_per_1m": 2.50,
        "output_per_1m": 10.00,
        "cache_discount": 0.50,  # 캐시 히트 시 input 가격 50%
    },
    "anthropic/claude-opus-4.7": {
        "input_per_1m": 15.00,
        "output_per_1m": 75.00,
        "cache_discount": 0.10,  # 90% 할인
    },
    "google/gemini-3.1-pro-preview": {
        "input_per_1m": 1.25,
        "output_per_1m": 5.00,
        "cache_discount": 1.00,  # 캐시 미지원
    },
}

def compute_cost(model, prompt_tokens, output_tokens, cached_tokens):
    p = MODEL_PRICING.get(model)
    if not p: return 0.0
    non_cached = prompt_tokens - cached_tokens
    input_cost = (
        non_cached / 1_000_000 * p["input_per_1m"]
        + cached_tokens / 1_000_000 * p["input_per_1m"] * p["cache_discount"]
    )
    output_cost = output_tokens / 1_000_000 * p["output_per_1m"]
    return round(input_cost + output_cost, 6)
```

#### 2-4. 집계 API

```python
# src/store/artifact_store.py
def get_run_cost(db_path, run_id) -> dict:
    """한 run의 총 비용과 Phase별 breakdown."""
    return {
        "total_usd": 0.234,
        "total_tokens": {"input": 12000, "output": 3400},
        "cache_hit_rate": 0.45,
        "by_phase": {
            "phase_3a": {"cost": 0.12, "calls": 1},
            "phase_4_structure": {"cost": 0.08, "calls": 1},
            ...
        }
    }

def get_project_cost(db_path, project_id) -> dict:
    """프로젝트 전체 비용."""
```

#### 2-5. 웹 UI 노출
프로젝트 상세 페이지에 "총 비용: $0.23 / 캐시 히트율: 45%" 표시.

### 테스트
- `tests/test_day125_cost_tracking.py` 신규
  - llm_utils mock 응답에 usage 포함 → DB 기록 확인
  - 모델별 비용 계산 정확성
  - 캐시 할인 반영
  - `db_path=None` 일 때 기록 없이 정상 동작 (하위호환)

### 예상 소요
- DB 스키마 + pricing 테이블: 0.5일
- llm_utils 확장 + 회귀 테스트: 1일
- 집계 API + UI 표시: 1일
- **합계 2.5일**

---

## 과제 3 · 웹 UI SSE (실시간 진행 상황)

### 현재 문제
- Phase 1~5 전체 실행 시 2~5분 대기
- 프런트는 polling 또는 완료 후에야 결과 표시
- 사용자는 "뭐가 진행 중인지" 알 수 없음

### 목표
Server-Sent Events (SSE) 로 각 Phase 시작/종료/에러 이벤트를 실시간 push.

### 설계

#### 3-1. 백엔드 SSE 엔드포인트

```python
# src/web/app.py
from fastapi.responses import StreamingResponse
import asyncio, json

@app.get("/runs/{run_id}/events")
async def run_events(run_id: str):
    async def event_stream():
        last_phase = None
        last_status = None
        while True:
            artifact = load_artifact(DB_PATH, run_id=run_id)
            if not artifact:
                yield f"event: error\ndata: {{\"msg\":\"not found\"}}\n\n"
                return

            phase = artifact.get("phase")
            status = artifact.get("run_status")

            # 상태 변화가 있을 때만 push
            if phase != last_phase or status != last_status:
                payload = {
                    "phase": phase,
                    "status": status,
                    "last_node": artifact.get("last_node"),
                }
                yield f"event: update\ndata: {json.dumps(payload)}\n\n"
                last_phase, last_status = phase, status

            # 종료 상태면 스트림 닫기
            if status in ("completed", "error", "verification_failed"):
                yield f"event: done\ndata: {{\"final\":\"{status}\"}}\n\n"
                return

            await asyncio.sleep(1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

#### 3-2. 프런트엔드

```javascript
// src/web/templates/run_detail.html
const es = new EventSource(`/runs/${runId}/events`);

es.addEventListener("update", (e) => {
    const data = JSON.parse(e.data);
    document.querySelector("#phase").textContent = data.phase;
    document.querySelector("#status").textContent = data.status;
    // Phase별 progress bar 갱신
});

es.addEventListener("done", (e) => {
    es.close();
    window.location.reload();  // 결과 화면으로
});

es.addEventListener("error", (e) => {
    es.close();
    // 에러 표시
});
```

#### 3-3. Phase 진행 시각화

프런트에 7단계 타임라인 표시:

```
[✓] Phase 0.5  [✓] Phase 1  [●] Phase 2  [ ] Phase 3 ...
                              ↑ 진행 중 (pulsing)
```

### 리스크
- SSE는 HTTP/1.1 connection 유지 → uvicorn worker 충분해야 함
- polling(1초) 방식이라 DB 부하 있음 → 5초로 조정 가능
- 연결 끊김 시 EventSource가 자동 재연결하지만 상태 동기화 주의

### 대안
진짜 실시간이 필요 없으면: **프런트에서 5초 polling** 으로 간단히 해결 가능.
Step 14에서는 SSE 구현, 문제 있으면 polling으로 fallback.

### 테스트
- `tests/test_day126_sse.py` 신규
  - FastAPI TestClient 로 SSE 엔드포인트 호출
  - DB 상태 업데이트 → 이벤트 수신 확인
  - 종료 상태 도달 → done 이벤트 후 스트림 close

### 예상 소요
- 백엔드 엔드포인트: 0.5일
- 프런트 EventSource + 타임라인 UI: 1일
- 테스트 + 디버깅: 0.5일
- **합계 2일**

---

## 전체 일정

| 과제 | 소요 | 우선순위 |
|---|---|---|
| Phase 2 병렬 | 1.5일 | **높음** (체감 속도 큰 개선) |
| 비용 추적 | 2.5일 | **중간** (운영 중요) |
| 웹 UI SSE | 2일 | 낮음 (polling으로 대체 가능) |

**전체 6일 예상** (버퍼 2일 포함 8일 잡는 게 안전)

### 권장 순서
1. 비용 추적 **먼저** — Phase 2 병렬 확대 전후 비용 차이를 측정하려면 먼저 있어야 함
2. Phase 2 병렬 — 사용자 체감 개선
3. SSE — 폴리시

---

## Definition of Done

- [ ] pytest 전체 passing (Step 14 완료 시 예상 430+)
- [ ] 프로젝트 상세 페이지에 비용 표시
- [ ] Phase 2 소요시간 before/after 비교 수치 확보
- [ ] SSE 스트림으로 Phase 진행 실시간 표시 (또는 polling fallback)
- [ ] `README.md` · `project_context.md` 갱신

---

## Step 14 이후 후보 (기록만)

- 배포 (Railway / Fly.io)
- SQLite → PostgreSQL 마이그레이션
- 멀티유저 (OAuth)
- v5: 에이전트 자동 실행 (Cursor handoff 제거)

이 문서에서는 다루지 않음.
