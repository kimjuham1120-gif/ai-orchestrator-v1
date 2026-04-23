# Phase 1·2·3 재설계 · 4-AI Deep Research 교차 합의

> 확정: 2026-04-24 (Day 123 직후)
> 근거: 사용자 결정 — 분해 제거, 4-AI Deep Research, 보류도 활용, $5 상한
> 범위: `phase_1`, `phase_2`, `phase_3` 재작업 + DB 스키마 확장

---

## 0. 핵심 설계 요약

### Before
```
Phase 1: raw_input → 서브주제 N개 분해
Phase 2: N 서브주제 × M 어댑터 = N×M 호출 (일반 모델)
Phase 3: 개별 결과 종합
```

### After
```
Phase 1: raw_input → 정제된 포괄 질의 1개 (Haiku 4.5)
Phase 2: 동일 질의 × 4 AI Deep Research = 4 호출 (병렬)
Phase 3: 4개 리포트 → 교차 합의 판정 → 2문서 합성
```

### 예상 비용 (프로젝트 1회)
| 단계 | 모델 | 비용 |
|---|---|---|
| Phase 0.5 | Haiku 4.5 | ~$0.001 |
| Phase 1 (질의 정제) | Haiku 4.5 | ~$0.002 |
| Phase 2 × 4 (Deep Research) | 4개 | **$3 ~ $8** |
| Phase 3 (합의 판정) | Haiku 4.5 | ~$0.05 |
| Phase 3 (2문서 합성) | Sonnet 4.6 | ~$0.10 |
| Phase 4 (감사관 4명) | 기존 | ~$0.30 |
| Phase 5 (피드백당) | Sonnet 4.6 | ~$0.05 |
| **합계 (기본 실행)** | — | **$3.5 ~ $8.5** |

BudgetGuard `$5` 상한으로 Tier 통제 필요. 초과 시 Deep Research 1개 어댑터 자동 스킵.

---

## 1. DB 스키마 확장 (`artifact_store.py`)

### 1-1. 신규 JSON 컬럼 추가

```python
_V5_NEW_COLUMNS = [
    ("refined_query",      "TEXT"),   # Phase 1 결과 (신규 의미)
    ("four_reports",       "TEXT"),   # Phase 2 결과 (4-AI Deep Research)
    ("consensus_claims",   "TEXT"),   # Phase 3 교차 합의 결과
    ("llm_calls",          "TEXT"),   # 비용 추적용 (Step 14-1과 공유)
]
```

`_JSON_COLS_V4`에 병합 (또는 `_V5` 로 분리). `_ensure_v4_columns` 확장.

### 1-2. `parallel_research` 컬럼 처리
- 기존 v4 컬럼이라 **삭제 X**
- 신규 로직은 `four_reports`만 사용
- 점진 전환: 기존 Phase 2 코드 제거 시점에 `parallel_research`를 deprecate 주석

### 1-3. `subtopics` 컬럼 처리
- Phase 1이 더 이상 분해 안 함 → `subtopics` 는 null
- 컬럼 유지 (v3/v4 호환), 쓰기 로직만 제거

---

## 2. Phase 1 재작성 — `phase_1_decompose.py`

### 2-1. 파일명 옵션
- **A. 유지** (`phase_1_decompose.py`) — 기존 import 깨지지 않음, 단 의미 혼선
- **B. 리네임** (`phase_1_refine.py`) — 깔끔, 리팩토링 비용 O

**권장: A (유지) + 내부 문서화**. 리네임은 v5에서.

### 2-2. 함수 시그니처

```python
@dataclass
class RefineResult:
    refined_query: Optional[str]
    status: str                       # "success" | "failed"
    error: Optional[str] = None
    original: Optional[str] = None    # 원본 raw_input 보존

    def to_dict(self) -> dict: ...


def refine_query(raw_input: str) -> RefineResult:
    """
    사용자 raw_input을 Deep Research가 잘 받는 포괄 질의로 재작성.

    특징:
    - 분해 X, 하나의 질의로
    - 명확성 보강 (맥락, 범위, 관점)
    - 한국어 유지

    실패 시 원본 raw_input 그대로 refined_query에 담아 반환 (fallback).
    """
```

### 2-3. 프롬프트

```python
PROMPT_REFINE_QUERY = """\
당신은 사용자의 요청을 '종합 리서치 AI'가 잘 이해할 수 있는 포괄 질의로 재작성하는 편집자입니다.

## 원칙
1. **쪼개지 말고 하나의 질의로** — 리서치 AI 내부에서 알아서 여러 측면을 탐색합니다.
2. **맥락·범위·관점 보강** — 사용자가 생략한 정보를 명시적으로 기입합니다.
3. **중립적 어조** — 특정 답을 유도하지 않습니다.
4. **한국어**

## 사용자 원본 요청
{raw_input}

## 출력 형식
재작성된 포괄 질의 텍스트만 출력. 설명, 목록, 코드 블록 없이.

예시:
- 입력: "카페 운영 가이드 문서 만들어줘"
- 출력: "개인 카페 창업자·초보 운영자를 위한 완전한 운영 가이드.
  개점 준비, 메뉴 구성, 원가 관리, 인력 관리, 고객 응대, 재고 관리,
  법규·세무, 마케팅·브랜딩을 모두 포함하여 최신 2026년 기준 실무 관점에서 정리."
"""
```

### 2-4. 모델 설정

```python
# phase_1_decompose.py 상단
PHASE_1_MODEL = os.environ.get("PHASE_1_MODEL", "anthropic/claude-haiku-4-5")
PHASE_1_TIMEOUT = float(os.environ.get("PHASE_1_TIMEOUT", "30.0"))
```

### 2-5. 테스트 수정
- 기존 "서브주제 N개 확인" 테스트 → "refined_query 1개 반환" 으로 대체
- `test_day116_phase_1.py` 재작성 (파일 없으면 `test_day128_phase_1_refine.py` 신규)

---

## 3. Phase 2 재작성 — `phase_2_*.py`

### 3-1. 어댑터 인터페이스 (4개 전부 동일)

```python
@dataclass
class DeepResearchResult:
    adapter_name: str                    # "perplexity" | "openai" | "gemini" | "claude"
    status: str                          # "success" | "failed" | "skipped_budget"
    report: Optional[str] = None         # 마크다운 리포트 본문
    claims: list[dict] = field(default_factory=list)
                                         # [{"text": str, "source": str}, ...]
    model_used: Optional[str] = None
    cost_usd: Optional[float] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None


async def run_deep_research(
    refined_query: str,
    adapter: str,
    budget_guard: Optional[BudgetGuard] = None,
) -> DeepResearchResult:
    ...
```

### 3-2. 4개 어댑터 구현 (파일 분리)

```
src/phases/phase_2_adapters/
    __init__.py
    perplexity_adapter.py    # sonar-deep-research (OpenRouter)
    openai_adapter.py         # o4-mini-deep-research (OpenAI Responses API)
    gemini_adapter.py         # gemini-3.1-pro + grounding (OpenRouter)
    claude_adapter.py         # claude-sonnet-4-6 + web_search (OpenRouter or 직접)
```

#### 각 어댑터 모델 기본값 (환경변수)

```python
ADAPTER_MODELS = {
    "perplexity": os.environ.get("RESEARCH_PERPLEXITY_MODEL", "perplexity/sonar-deep-research"),
    "openai":     os.environ.get("RESEARCH_OPENAI_MODEL",     "openai/o4-mini-deep-research"),
    "gemini":     os.environ.get("RESEARCH_GEMINI_MODEL",     "google/gemini-3.1-pro-preview"),
    "claude":     os.environ.get("RESEARCH_CLAUDE_MODEL",     "anthropic/claude-sonnet-4-6"),
}

ADAPTER_TIMEOUTS = {
    "perplexity": float(os.environ.get("RESEARCH_TIMEOUT_SECS", "300")),  # 5분
    "openai":     float(os.environ.get("RESEARCH_TIMEOUT_SECS", "300")),
    "gemini":     float(os.environ.get("RESEARCH_TIMEOUT_SECS", "300")),
    "claude":     float(os.environ.get("RESEARCH_TIMEOUT_SECS", "300")),
}
```

#### OpenAI Deep Research — 별도 API (주의)
`o4-mini-deep-research`는 **Responses API**만 지원 (OpenRouter Chat Completions 불가능 가능성). 구현 우선순위:

- **옵션 1**: 직접 OpenAI Responses API 호출 (별도 `OPENAI_API_KEY` 필요)
- **옵션 2**: OpenRouter에 해당 엔드포인트 있는지 확인
- **옵션 3**: 초기엔 `openai/gpt-5.4 + web_search` 로 대체, Deep Research는 추후 추가

**권장: 옵션 3 부터** (별도 키 발급 리스크 피함).

#### Claude Research — 대체
Claude Research는 API 없음. **Sonnet 4.6 + web_search tool** 로 구현. OpenRouter가 tool 지원하는지 확인. 안 되면:
- 직접 Anthropic API 사용 (별도 `ANTHROPIC_API_KEY`)
- 또는 더 단순하게: Sonnet 4.6에게 프롬프트만 주고 `web_search` 없이 답변 받음 (품질 저하 수용)

### 3-3. 병렬 실행 + 예산 가드

```python
async def run_phase_2_async(
    refined_query: str,
    budget_guard: BudgetGuard,
) -> dict:
    """
    4-AI Deep Research 동시 실행.

    Returns:
      {
        "four_reports": {
          "perplexity": DeepResearchResult,
          "openai":     DeepResearchResult,
          "gemini":     DeepResearchResult,
          "claude":     DeepResearchResult,
        },
        "success_count": int,
        "total_cost_usd": float,
        "error": Optional[str],
      }
    """
    adapters = ["perplexity", "openai", "gemini", "claude"]

    # 예산 사전 체크 — 4개 × 평균 $1.5 = $6 예상 → $5 상한 근접
    if budget_guard.remaining < 4.0:
        # 가장 저렴한 것만 (perplexity + gemini) → $2 수준
        adapters = ["perplexity", "gemini"]

    tasks = [run_deep_research(refined_query, a, budget_guard) for a in adapters]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    four_reports = {}
    for adapter, result in zip(adapters, results):
        if isinstance(result, Exception):
            four_reports[adapter] = DeepResearchResult(
                adapter_name=adapter,
                status="failed",
                error=str(result),
            )
        else:
            four_reports[adapter] = result

    success_count = sum(1 for r in four_reports.values() if r.status == "success")
    total_cost = sum(r.cost_usd or 0 for r in four_reports.values())

    return {
        "four_reports": four_reports,
        "success_count": success_count,
        "total_cost_usd": total_cost,
        "error": None if success_count >= 2 else "2개 미만 성공 — 합의 판정 불가",
    }
```

### 3-4. sync 진입점 (handlers.py가 사용)

```python
def run_phase_2(refined_query: str, budget_guard: BudgetGuard) -> dict:
    return asyncio.run(run_phase_2_async(refined_query, budget_guard))
```

### 3-5. 의존성 추가
`requirements.txt`:
```
httpx[async]   # 이미 있을 가능성 높음
# (OpenAI Deep Research 쓰면 openai SDK도)
```

### 3-6. 테스트 (`test_day129_phase_2_fourai.py` 신규)
- Mock으로 4개 어댑터 성공 케이스
- 1개 실패 → 나머지 완주
- 2개 미만 성공 → error 반환
- BudgetGuard 상한 근접 시 2개로 축소
- 예산 초과 시 `skipped_budget` 상태

---

## 4. Phase 3 재작성 — `phase_3_synthesize.py`

### 4-1. 입력 구조 변경
- **기존**: `parallel_research: dict`
- **변경**: `four_reports: dict[str, DeepResearchResult]`

### 4-2. 새로운 단계 추가 — 교차 합의 판정

```python
@dataclass
class ConsensusClaim:
    text: str                            # 주장 본문
    agreed_by: list[str]                 # ["perplexity", "openai", ...]
    agreement_count: int                 # len(agreed_by)
    status: str                          # "confirmed" | "pending" | "rejected"
    sources: list[str] = field(default_factory=list)


def run_consensus_judgment(
    four_reports: dict,
) -> list[ConsensusClaim]:
    """
    4개 리포트의 claims를 모아 LLM 판정관에게 전달 → 교차 합의 클러스터링.

    판정 규칙:
      동의 AI 수 4 → confirmed
      동의 AI 수 3 → confirmed
      동의 AI 수 2 → pending (Phase 3 합성에 출처 명시하며 사용)
      동의 AI 수 1 → rejected (제외)

    모델: Haiku 4.5 (분류·클러스터링)
    """
```

### 4-3. 판정관 프롬프트

```python
PROMPT_CONSENSUS = """\
당신은 '교차 합의 판정관'입니다. 4개의 AI가 같은 질문에 대해 작성한 리서치 리포트를 받아서,
사실 주장(claim)이 몇 개의 AI에 의해 지지되는지 판정합니다.

## 판정 규칙
1. 각 AI 리포트에서 **개별 사실 주장**을 추출합니다.
2. **의미상 같은 주장**은 같은 claim으로 묶습니다 (문구가 달라도).
3. 각 claim이 몇 개의 AI에 의해 주장되었는지 세어 `agreed_by` 리스트에 담습니다.
4. 다음 규칙으로 status 부여:
   - 4개 모두 동의 → "confirmed"
   - 3개 동의 → "confirmed"
   - 2개 동의 → "pending"
   - 1개만 주장 → "rejected"

## 입력
### Perplexity 리포트
{perplexity_report}

### OpenAI 리포트
{openai_report}

### Gemini 리포트
{gemini_report}

### Claude 리포트
{claude_report}

## 출력 형식 (JSON)
```json
{{
  "claims": [
    {{
      "text": "주장 본문 (한국어)",
      "agreed_by": ["perplexity", "openai"],
      "agreement_count": 2,
      "status": "pending",
      "sources": ["출처 URL 또는 발행처"]
    }}
  ]
}}
```

JSON만 출력. 설명 없이.
"""
```

### 4-4. `call_llm_json` 사용 (Step 14-2와 병합)

판정관 JSON 파싱 실패 시 재시도 필수 → `call_llm_json` 래퍼 먼저 구현.

### 4-5. 2문서 합성 로직 변경

기존 3a/3b 합성 로직은 유지하되 **입력만 변경**:

```python
def synthesize_documents(
    raw_input: str,
    refined_query: str,
    four_reports: dict,
    consensus_claims: list[ConsensusClaim],
    feasibility: Optional[dict] = None,
) -> SynthesizeResult:
    ...
```

합성 프롬프트에 **합의 등급별로 섹션 분리**해서 제공:

```python
def _format_claims_for_prompt(claims: list[ConsensusClaim]) -> str:
    confirmed = [c for c in claims if c.status == "confirmed"]
    pending   = [c for c in claims if c.status == "pending"]

    lines = []
    lines.append("## ✅ 확정 사실 (3~4개 AI 동의)")
    for c in confirmed:
        lines.append(f"- {c.text} (동의: {', '.join(c.agreed_by)})")

    lines.append("\n## ⚠️ 보류 사실 (2개 AI 동의) — 출처 명시 필요")
    for c in pending:
        lines.append(f"- {c.text} (동의: {', '.join(c.agreed_by)})")

    return "\n".join(lines)
```

**3a 프롬프트에는 confirmed + pending 모두 포함, pending은 "일부 AI 주장"으로 명시**.
**3b 프롬프트에도 동일, 단 사용자 톤에 맞춰 재구성**.

### 4-6. 모델 설정

```python
# phase_3_synthesize.py 상단
SYNTHESIS_MODEL    = os.environ.get("SYNTHESIS_MODEL", "anthropic/claude-sonnet-4-6")  # 변경됨
SYNTHESIS_TIMEOUT  = float(os.environ.get("SYNTHESIS_TIMEOUT", "90.0"))

CONSENSUS_MODEL    = os.environ.get("CONSENSUS_MODEL", "anthropic/claude-haiku-4-5")  # 신규
CONSENSUS_TIMEOUT  = float(os.environ.get("CONSENSUS_TIMEOUT", "60.0"))
```

### 4-7. 테스트 수정 (`test_day117_phase_3.py`)
- 기존 테스트 대부분 유지 가능
- **추가**: `run_consensus_judgment` 단위 테스트 (4개 리포트 mock → claims 분류)
- **추가**: 합성 프롬프트에 confirmed/pending 섹션 포함 확인

---

## 5. 비용 가드 (`src/utils/budget_guard.py`)

```python
from dataclasses import dataclass, field
import os

@dataclass
class BudgetGuard:
    project_id: str
    max_cost_usd: float = field(
        default_factory=lambda: float(os.environ.get("BUDGET_PROJECT_MAX_USD", "5.0"))
    )
    current_cost: float = 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, self.max_cost_usd - self.current_cost)

    def exceeded(self) -> bool:
        return self.current_cost >= self.max_cost_usd

    def can_afford(self, estimated_cost: float) -> bool:
        return self.current_cost + estimated_cost <= self.max_cost_usd

    def consume(self, cost: float) -> None:
        self.current_cost += cost

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "max_cost_usd": self.max_cost_usd,
            "current_cost": round(self.current_cost, 4),
            "remaining": round(self.remaining, 4),
            "exceeded": self.exceeded(),
        }
```

### 5-1. 사용처
- Phase 2 호출 전 `budget_guard.remaining` 확인
- 각 어댑터 완료 후 `budget_guard.consume(cost)`
- Phase 5 피드백 루프에서도 사용 (5회차 이상 시 경고)

### 5-2. 저장
실행 중: 메모리 (dataclass).
영속화: DB의 `cost_tracking` 컬럼 또는 별도 테이블 (Step 14-1과 연계).

---

## 6. Phase별 모델 확정표

환경변수 기본값으로 적용:

| Phase | 역할 | 모델 | 변경 근거 |
|---|---|---|---|
| 0.5 | 게이트 | `anthropic/claude-haiku-4-5` | 단순 yes/no, 다운그레이드 |
| 1 | 질의 정제 | `anthropic/claude-haiku-4-5` | 단순 편집, 다운그레이드 |
| 2 Perplexity | Deep Research | `perplexity/sonar-deep-research` | 새 구성 |
| 2 OpenAI | Deep Research | `openai/o4-mini-deep-research` | 새 구성 (또는 fallback GPT-5.4+search) |
| 2 Gemini | Deep Research | `google/gemini-3.1-pro-preview` | grounding 활용 |
| 2 Claude | Deep Research | `anthropic/claude-sonnet-4-6` | web_search 활용 |
| 3 합의 판정 | 클러스터링 | `anthropic/claude-haiku-4-5` | 분류 작업 |
| 3a 기반정보 | 문서 합성 | `anthropic/claude-sonnet-4-6` | GPT-5.4 → Sonnet (캐싱 유리) |
| 3b 목표문서 | 문서 합성 | `anthropic/claude-sonnet-4-6` | 동일 |
| 4 구조 감사관 | 논리 | `anthropic/claude-opus-4-7` | 유지 (변경 금지) |
| 4 균형 감사관 | 편향 | `anthropic/claude-sonnet-4-6` | GPT-5.4 → Sonnet (검토) |
| 4 사실 감사관 | 사실 | `google/gemini-3.1-pro-preview` | 유지 |
| 4 통합 | 편집 | `anthropic/claude-sonnet-4-6` | GPT-5.4 → Sonnet |
| 5 피드백 | 재작성 | `anthropic/claude-sonnet-4-6` | GPT-5.4 → Sonnet |
| 6 브리지 | 트랙 결정 | `anthropic/claude-haiku-4-5` | 단순 분류 |
| 7 planner | 실행 계획 | `anthropic/claude-sonnet-4-6` | 중급 추론 |
| 7 builder | 빌더 | `anthropic/claude-sonnet-4-6` | 동일 |

### `.env` 추가 항목
```bash
# Phase별 모델 (Step 14-1 이후 활성화)
PHASE_0_5_MODEL=anthropic/claude-haiku-4-5
PHASE_1_MODEL=anthropic/claude-haiku-4-5
CONSENSUS_MODEL=anthropic/claude-haiku-4-5
SYNTHESIS_MODEL=anthropic/claude-sonnet-4-6
FEEDBACK_MODEL=anthropic/claude-sonnet-4-6
BRIDGE_MODEL=anthropic/claude-haiku-4-5
PLANNER_MODEL=anthropic/claude-sonnet-4-6
BUILDER_MODEL=anthropic/claude-sonnet-4-6

# Phase 2 Deep Research
RESEARCH_PERPLEXITY_MODEL=perplexity/sonar-deep-research
RESEARCH_OPENAI_MODEL=openai/o4-mini-deep-research
RESEARCH_GEMINI_MODEL=google/gemini-3.1-pro-preview
RESEARCH_CLAUDE_MODEL=anthropic/claude-sonnet-4-6

# 비용 가드
BUDGET_PROJECT_MAX_USD=5.0
```

---

## 7. 작업 PC 적용 순서

### Step A · 준비 (0.5일)
1. `BudgetGuard` 구현 (`src/utils/budget_guard.py`)
2. `call_llm_json` 구현 (`src/utils/llm_utils.py`) — Step 14-2 선행
3. DB 스키마 신규 컬럼 추가 (`refined_query`, `four_reports`, `consensus_claims`)
4. 환경변수 추가 (`.env`)

### Step B · Phase 1 전환 (0.5일)
1. `phase_1_decompose.py` 내부 재작성 (분해 → 정제)
2. 모델을 Haiku로 고정
3. 테스트 재작성 (`test_day116` or `test_day128`)

### Step C · Phase 2 재구성 (2일 · 핵심)
1. `phase_2_adapters/` 디렉터리 생성
2. 4개 어댑터 구현 (순서: perplexity → gemini → claude → openai)
3. 각 어댑터 비용 측정 로직 통합
4. `run_phase_2_async` 통합 함수
5. BudgetGuard 연동
6. 테스트 (`test_day129_phase_2_fourai.py`)

### Step D · Phase 3 확장 (1일)
1. `run_consensus_judgment` 구현
2. `call_llm_json` 활용 JSON 재시도
3. `synthesize_documents` 시그니처 변경 (four_reports + consensus_claims 입력)
4. 프롬프트 수정 (confirmed/pending 섹션)
5. 테스트 재작성

### Step E · handlers/웹 UI 연동 (0.5일)
1. `web/handlers.py::handle_phase_1` — 분해 → 정제로 변경
2. `web/handlers.py::handle_phase_2` — async 호출
3. 웹 UI 텍스트 "서브주제" → "리서치 질의" 변경
4. 프로젝트 상세 페이지에 **비용 표시** 추가

### Step F · 회귀 테스트 + 실측 (0.5일)
1. 전체 pytest passing 확인
2. 실제 프로젝트 1회 실행 → 비용 측정
3. 측정치 공유 → v3 조정

**합계: 약 5일**

---

## 8. 리스크 & 대응

### 8-1. Deep Research API 접근 불가
| 어댑터 | 리스크 | 대응 |
|---|---|---|
| Perplexity sonar-deep-research | OpenRouter 제공 확인 필요 | 대체: `perplexity/sonar-pro` |
| OpenAI o4-mini-deep-research | Responses API 필요, OpenRouter 미제공 가능성 | 대체: `openai/gpt-5.4` + 자체 web_search 루프 |
| Gemini 3.1 Pro + grounding | OpenRouter 기본 grounding 불확실 | 대체: 일반 gemini-3.1-pro, 웹 검색 수동 |
| Claude Sonnet 4.6 + web_search | OpenRouter tool 지원 불확실 | 대체: Anthropic 직접 API |

**대응 원칙**: 초기엔 가장 단순한 방법으로 구현 → 실제 품질 측정 → 필요 시 업그레이드.

### 8-2. 합의 판정 품질
Haiku 4.5가 claims 클러스터링을 잘 할지 검증 필요. 실패 시 Sonnet 4.6로 업그레이드 (비용 3배).

### 8-3. Phase 2 시간 초과
4개 × 최대 5분 = 20분 가능. **병렬이므로 실제 소요는 가장 느린 것 기준 ~5분**. 단 uvicorn request timeout 확인 필요.

### 8-4. 예산 초과 중단 시 UX
`skipped_budget` 상태 어댑터 발생 시 사용자에게 명확히 표시. 부분 결과로 Phase 3 진행 (성공 ≥ 2개면 OK).

---

## 9. 테스트 전략

### 기존 passing 유지
- `test_day117_phase_3.py` — 입력 구조 변경, 새 테스트로 재작성
- 기존 Phase 1 테스트 — 재작성
- 기존 Phase 2 테스트 — 전부 deprecate 또는 재작성

### 신규
- `test_day128_phase_1_refine.py` — 질의 정제
- `test_day129_phase_2_fourai.py` — 4-AI 병렬
- `test_day130_consensus.py` — 교차 합의 판정
- `test_day131_budget_guard.py` — BudgetGuard

### 목표
현재 403 passed → 재작성·추가 후 **약 430 passed** 예상.

---

## 10. 이 설계의 한계·약점

1. **합의 판정이 LLM 의존** — Haiku 실수 시 confirmed를 rejected로 잘못 분류 가능. 판정관 프롬프트 반복 튜닝 필요.
2. **의미 중복 주장의 분류** — "A=B" 와 "B=A"를 다른 주장으로 보면 합의 실패. LLM 판정관이 어느 정도는 처리하지만 완벽하지 않음.
3. **편향 위험** — 4개 AI가 모두 같은 오해를 공유할 때 **"확정"으로 잘못 분류**. 현재는 막을 방법 없음. 사용자가 피드백 단계에서 교정.
4. **비용 변동성** — Deep Research는 쿼리마다 비용 편차 큼. BudgetGuard가 있어도 1회당 $3~8 요동.
5. **처음엔 OpenAI Deep Research 못 쓸 수도** — OpenRouter 지원 확인 필요. 그동안은 3-AI(Perplexity+Gemini+Claude)로 임시 운영.

---

## 11. v2 이후 검토 사항

- Phase 2를 **Tier 1 (일반) / Tier 2 (Deep)** 토글로 분리 (사용자 요청 있으면)
- 합의 판정 알고리즘 개선 (임베딩 기반 유사도)
- 피드백 루프에서도 교차 검증 적용
- Perplexity/OpenAI/Gemini 전용 API 키 분리 관리

---

## 변경 이력
- **v1** (Day 123+, 현재): Phase 1/2/3 재설계 확정. 4-AI Deep Research 교차 합의, BudgetGuard $5 상한.
