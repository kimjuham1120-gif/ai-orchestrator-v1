# 토큰 절약 자료 검증 및 v4 적용 전략

> 사용자 제공 자료 4섹션 (Claude / Gemini / GPT / Perplexity)을 **검증**하고
> **우리 프로젝트(ai-orchestrator-v4)에 실제로 적용 가능한 것**만 추려낸 문서.
> 추가로 **Phase 단계별 모델 선택**을 재점검.

---

## 1. 자료 검증 결과 요약

| 자료 주장 | 검증 결과 | 프로젝트 적용 가능성 |
|---|---|---|
| Claude Code `/clear` `/compact` 습관화 | ✅ 사실 — 공식 문서 확인 | ⚠️ **우리 앱엔 직접 적용 X** (아래 설명) |
| Opus 4~5배 비쌈 | ✅ 대략 맞음 (Opus $5/$25, Sonnet $3/$15 → input 1.67×, output 1.67×) ※ **"4~5배"는 과장**. 하이쿠 대비 5배 맞음 | ✅ **Opus 남용 주의** 원칙만 적용 |
| **Advisor Strategy** (Opus 어드바이저 + Sonnet/Haiku 익스큐터) | ✅ 사실 — 2026-04-09 beta, 11.9% 비용↓ + 2.7pp 성능↑ | 🟢 **매우 유용** — Phase 4 감사관 구성에 적용 가능 |
| Haiku + Opus advisor = Sonnet 대비 85% 저렴 | ✅ 사실 (BrowseComp 벤치) | 🟢 Phase 2 리서치에 적용 가능 |
| `.claudeignore` / `claude.md` 다이어트 | ✅ 사실 | ❌ **해당 없음** — 우리는 Claude Code 안 씀 |
| Gemini Context Caching (75% 할인) | ⚠️ 숫자 확인 필요 — Anthropic 캐시는 **90% 할인**(0.1×), OpenAI는 50% 할인. Google은 2.5 Pro/Flash에서 캐시 가능한데 구체 할인율은 변동 | 🟡 Gemini 어댑터에 적용 가능 (Phase 2) |
| Perplexity Follow-up 최소화 | ⚠️ 사실이지만 **API는 stateless** — 이건 UI(웹/앱) 한정 조언 | 🟡 우리는 단발 호출이라 이미 OK |
| GPT Prompt Caching 1024토큰↑ 50% 할인 | ✅ 사실 확인 | 🟢 Phase 0.5/1/3/4/5 모두 해당 |

### 특히 중요한 발견 — "Advisor Strategy"

자료에 살짝 나왔지만(Opus Plan) **이걸 제대로 알면 프로젝트 구조가 바뀔 수 있습니다.**

- Anthropic이 2026-04-09 발표
- `anthropic-beta: advisor-tool-2026-03-01` 헤더 + `advisor_20260301` tool config
- **1 API 호출 안에서** Sonnet/Haiku가 돌다가 막히면 Opus에게 조언 요청
- 외부 orchestration 필요 없음 → 지금 우리 Phase 4 구조를 단순화할 수 있음

단 **OpenRouter가 이 beta feature를 프록시할지는 불확실**. 확인 필요.

---

## 2. 자료 맹신하면 안 되는 이유 5가지

### 2-1. "Claude Code 팁"은 우리에게 **거의 해당 없음**

자료의 섹션 1(Claude Code)은 **CLI/터미널 도구인 Claude Code** 얘기. 우리는:
- `httpx`로 **OpenRouter API 직접 호출**
- stateless 단발 호출 (`call_llm(prompt, ...)`)
- 대화 컨텍스트 축적 안 함 → `/clear` 자체가 필요 없음

**다만 패턴만 배운다**:
- **"주제 전환 시 컨텍스트 초기화"** = Phase 간 독립 실행 (이미 함)
- **"압축"** = Phase 5 피드백 이력 압축 (Step 14-3에 넣음)
- **"이그노어 파일"** = 리서치 결과 중 중복 제거 (적용 가능)

### 2-2. "Opus 4~5배"는 2024년 숫자. 2026년 현재 다름

| 모델 | 2026 input($/1M) | 2026 output($/1M) |
|---|---|---|
| Claude Opus 4.7 / 4.6 | $15 (우리 context) 또는 $5 (eval) ⚠️ | $75 또는 $25 ⚠️ |
| Claude Sonnet 4.6 | $3 | $15 |
| Claude Haiku 4.5 | $1 | $5 |

※ **Opus 가격이 자료마다 다르게 보임** — Anthropic 공식 $5/$25 vs 우리 project_context의 $15/$75. 이유는:
- 자료 A (evolink.ai): **$5/$25**
- 자료 B (brainroad): **$5/$25** (Opus 4.6)
- project_context.md: **$15/$75** — 아마 **이전 Opus 3 시절 가격** 그대로 복붙한 것

**액션**: `model_pricing.py` 만들 때 **공식 가격으로 재확인** 필수.

### 2-3. "Haiku 위임" 조언 — 감사관에는 적용 금지

자료는 "단순 리서치·파일 단순 수정은 하이쿠"라고 함. 하지만 **우리 Phase 4 감사관**에 Haiku를 쓰면:
- 구조 감사관 (Opus): 논리 구조 심층 분석 → **Opus 유지 필수**
- 사실 감사관 (Gemini): 사실 검증, 웹 탐색 → **Gemini 유지**
- 균형 감사관 (현재 GPT-5.4): 편향 중립화 → Sonnet/Haiku로 **다운그레이드 가능**

감사관 역할은 가볍지 않음. 잘못 다운그레이드하면 **품질 붕괴**.

### 2-4. Perplexity 조언은 UI 전용

자료의 "후속 질문 최소화", "컬렉션 격리" 등은 **Perplexity 웹 앱** 이야기.

우리는 **Perplexity API(sonar)** 직접 호출 → stateless → 이미 최적.
대신 **API 레벨 최적화**가 따로 있음:
- `search_recency_filter="month"` — 오래된 웹 결과 제외 (토큰↓)
- `search_domain_filter=["gov", "edu"]` — 신뢰도 높은 도메인만
- `return_citations=False` — citation 토큰 제거 (약 20% 절감)
- 모델: `sonar` vs `sonar-pro` vs `sonar-deep-research` 가격 차 3~10배

### 2-5. Gemini "200만 토큰의 함정"은 우리에게도 적용

자료 지적: "빈 공간 많다고 다 때려넣으면 환각". 이건 맞음.

**우리 Phase 2**: Gemini를 리서치 어댑터로 쓰는데, 만약 "관련 자료 전부 넣고 요약해줘" 식이면 토큰 낭비 + 품질 저하. **서브주제 단위로 좁혀서 질문** (이미 잘 하고 있는지 확인 필요).

---

## 3. Phase 단계별 모델 전략 재검토

> **목표**: 각 Phase의 **역할 특성**에 맞는 모델 선택 + 비용 최적화

### 현재 구성 (project_context.md 기준)

| Phase | 역할 | 현재 모델 (추정/명시) |
|---|---|---|
| 0.5 | 게이트 (yes/no 판정) | 미상 (LLM 호출) |
| 1 | 서브주제 분해 | 미상 |
| 2 | 병렬 리서치 | Gemini + GPT + Perplexity |
| 3a | 기반정보 문서 | `openai/gpt-5.4` |
| 3b | 목표 산출물 초안 | `openai/gpt-5.4` |
| 4 구조 감사관 | 논리 구조 | `anthropic/claude-opus-4.7` |
| 4 균형 감사관 | 편향 중립화 | `openai/gpt-5.4` |
| 4 사실 감사관 | 사실 검증 | `google/gemini-3.1-pro-preview` |
| 4 통합 LLM | 고도화 편집 | `openai/gpt-5.4` |
| 5 | 피드백 재작성 | `openai/gpt-5.4` |
| 6 | 트랙 결정 (app/doc) | 미상 |
| 7 planner | 실행 계획 | 미상 |
| 7 builder | 코드 생성 계획 | 미상 |

### ⚠️ 개선 제안 (단계별)

#### Phase 0.5 — **Haiku로 다운그레이드 강력 권장**
**이유**:
- 판정이 **yes/no + 간단한 사유** → 추론 깊이 불필요
- 현재 Sonnet/GPT-5 쓰면 **2~5배 낭비**
- Haiku 4.5: $1/$5, 응답 속도도 빠름

**제안**: `PHASE_0_5_MODEL=anthropic/claude-haiku-4-5`

#### Phase 1 — **Haiku 또는 Sonnet**
**이유**:
- 사용자 요청 → 서브주제 3~7개로 분해 → 단순 분류 작업
- JSON 포맷만 맞추면 OK
- Haiku로 충분

**제안**: `PHASE_1_MODEL=anthropic/claude-haiku-4-5`
**리스크**: JSON 형식 깨짐 가능성 ↑ → Step 14-2 `call_llm_json` 재시도와 함께

#### Phase 2 — **현재 구성 유지 + 최적화**
**이유**:
- 다양한 프로바이더 병렬 = 편향 방지 핵심 설계
- 어댑터별 역할 분담 의미 있음

**최적화**:
- **Gemini**: 2.5 Flash로 전환 검토 (Pro 대비 10배 저렴, 간단 리서치엔 Flash 충분)
- **Perplexity**: `sonar` (기본) 사용, `sonar-pro`는 deep research 시만
- **GPT**: Prompt Caching 활용 (시스템 프롬프트 반복분 50% 할인)

**제안**:
- `RESEARCH_GEMINI_MODEL=google/gemini-3.1-flash`
- `RESEARCH_PERPLEXITY_MODEL=perplexity/sonar`

#### Phase 3a (기반정보 문서) — **Sonnet이 적절**
**이유**:
- 리서치 정리 → 구조화 → 범용 문서. 중급 추론 필요
- GPT-5.4 대신 Sonnet 4.6 써도 품질 유사 + 캐싱 유리
- Anthropic 캐시는 90% 할인 (OpenAI는 50%)

**제안**: `SYNTHESIS_3A_MODEL=anthropic/claude-sonnet-4-6`

#### Phase 3b (목표 산출물) — **Sonnet 또는 GPT 유지**
**이유**:
- 사용자 맞춤 결과물 — 문체·톤 중요
- GPT-5.4가 강점, 유지 가능

**제안**: 현재 GPT-5.4 유지. 나중에 A/B 테스트로 비교.

#### Phase 4 — **Advisor Strategy 검토**
**핵심 개선 가능성**:

**방안 A (현재 유지 + 약간 최적화)**:
- 구조 감사관: Opus 유지 (대체 불가)
- 균형 감사관: **GPT-5.4 → Sonnet 4.6 다운그레이드** 검토
- 사실 감사관: **Gemini 3.1 Pro → Gemini 3.1 Flash** (간단 사실 확인은 Flash 충분)
- 통합 LLM: Sonnet 4.6

**방안 B (Advisor Strategy 도입 — 실험적)**:
- Sonnet 실행 + 어려운 판정만 Opus 호출
- 11.9% 비용 절감 가능 (Anthropic 벤치)
- 단 OpenRouter 지원 확인 필요

**제안**: 방안 A부터. B는 Step 15+.

#### Phase 5 — **Sonnet 4.6**
**이유**:
- 피드백 반영 = 편집 작업, Sonnet 강점
- Opus 불필요 / Haiku는 품질 부족

**제안**: `FEEDBACK_MODEL=anthropic/claude-sonnet-4-6`

#### Phase 6 — **Haiku**
**이유**:
- 트랙 결정(app/doc) = 단순 분류
- 판정만 명확하면 됨

**제안**: `BRIDGE_MODEL=anthropic/claude-haiku-4-5`

#### Phase 7 planner — **Opus 또는 Sonnet + Opus Advisor**
**이유**:
- 실행 계획 수립 = 심층 추론
- Opus 값어치 있음

**제안**:
- 기본: `PLANNER_MODEL=anthropic/claude-sonnet-4-6`
- 복잡 작업일 때만 Opus

#### Phase 7 builder — **Sonnet**
**이유**:
- 코드 생성은 Sonnet이 표준
- Opus 과다 / Haiku 부족

**제안**: `BUILDER_MODEL=anthropic/claude-sonnet-4-6`

---

## 4. 비용 비교 시뮬레이션

### Before (현재 추정)
1회 실행 기준 (단순한 요청):
- Phase 0.5~6 전체 LLM 호출 약 10~15회
- 대부분 GPT-5.4 / Opus / Gemini Pro 사용
- **예상 비용: $0.40~1.20**

### After (제안대로 다운그레이드)
- Phase 0.5, 1, 6 → Haiku (비용 1/5)
- Phase 2 Gemini → Flash (비용 1/10)
- Phase 3a, 5, 7 → Sonnet (비용 40% 수준 + 캐싱 90%)
- Phase 4 균형/사실 감사관 → Sonnet/Flash
- **예상 비용: $0.15~0.50 (약 60~70% 절감)**

단 검증 필요 — 실제 측정은 **Step 14-1 비용 추적** 완성 후 A/B 테스트.

---

## 5. 실전 적용 체크리스트

### 즉시 적용 가능 (Step 14-1과 함께)
- [ ] `model_pricing.py` 에 **정확한 2026 가격** 반영 (Opus 4.7 = $5/$25)
- [ ] Phase별 모델 환경변수 분리 (`PHASE_0_5_MODEL`, `PHASE_1_MODEL`, ...)
- [ ] Gemini 어댑터에 Flash/Pro 선택 옵션
- [ ] Perplexity 어댑터에 `search_recency_filter`, `return_citations=False` 옵션

### 중기 (Step 14-3, 14-4)
- [ ] JSON 재시도 활성화 (Haiku 다운그레이드 대비)
- [ ] 프롬프트 길이 조정 (캐싱 기준 4000자 → 모델별 최적화)
- [ ] 캐시 히트율 측정 → 캐시 안 걸리는 프롬프트 구조 개선

### 장기 (Step 15+)
- [ ] Advisor Strategy 실험 (Anthropic 직접 API 필요할 수 있음)
- [ ] Batch API 검토 (50% 할인, 실시간 아닌 파이프라인에 유용)
- [ ] A/B 테스트 프레임워크 (같은 입력 다른 모델 비교)

---

## 6. 변경 제안 — `project_context.md` 업데이트

현재 "3감사관 구성(변경 금지)"에 명시된 모델 표가 있는데, 이 분석 후:

| 감사관 | 현재 | **제안** |
|---|---|---|
| 구조 감사관 | `claude-opus-4.7` | **유지** (대체 불가) |
| 균형 감사관 | `gpt-5.4` | `claude-sonnet-4-6` (검토) |
| 사실 감사관 | `gemini-3.1-pro-preview` | `gemini-3.1-flash` (검토, 정확도 벤치 후) |
| 통합 LLM | `gpt-5.4` | `claude-sonnet-4-6` (캐싱 우위) |

**중요**: "변경 금지"는 설계 원칙이니 실제 변경 전 **A/B 테스트로 품질 검증** 필수.

---

## 7. 최종 권고

### DO (지금 바로)
1. `model_pricing.py` 작성 시 **공식 2026 가격**으로
2. **Phase별 모델 환경변수** 분리 — 수정 없이 조정 가능하게
3. `project_context.md`의 Opus 가격 오류 수정 ($15/$75 → $5/$25)

### DON'T
1. 자료만 믿고 Phase 4 감사관 **일괄 Haiku 다운그레이드** 하지 말 것
2. `/clear` `/compact` 기능 **직접 구현 시도 X** (우리는 stateless)
3. Advisor Strategy 무조건 도입 X (OpenRouter 지원 확인 후)

### MEASURE (적용 후)
- Step 14-1 비용 추적으로 **before/after 수치** 기록
- 품질 저하 없는지 Phase별 **수동 검수** (몇 건 샘플링)
- 한 달 운영 후 결과 공유 → Step 15 방향 결정

---

## 자료 각주 (검증 출처)

- Claude Code /clear /compact: code.claude.com/docs, claude.com/blog (공식 확인)
- Advisor Strategy: claude.com/blog/the-advisor-strategy (2026-04-09, 공식)
- Claude 2026 가격: evolink.ai, brainroad (독립 소스 교차 확인)
- OpenAI Prompt Caching 50% / 1024토큰↑: lemondata.cc (공식 문서 링크)
- Anthropic cache 90% 할인: evolink.ai (0.1× 배수)

**자료와 다른 점**:
- 자료 "Gemini 75% 할인" → 검증 불가 (Google 공식 문서 재확인 필요)
- 자료 "Opus 4~5배" → 2026 기준 Sonnet 대비 1.67배, Haiku 대비 5배
