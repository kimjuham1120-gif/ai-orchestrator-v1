# Setup Guide — ai-orchestrator (Day 65~72 반영)

## 빠른 시작

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
python -m src.cli
```

## 환경변수

### 필수

```env
OPENROUTER_API_KEY=sk-or-...
GEMINI_API_KEY=AIza...
```

### GPT Deep Research

```env
OPENAI_API_KEY=sk-...
GPT_RESEARCH_MODEL=openai/o4-mini-deep-research  # 심층리서치 권장
GPT_RESEARCH_TIMEOUT=120.0
GPT_RESEARCH_MAX_TOKENS=2000
```

### Gemini Deep Research

```env
GEMINI_API_KEY=AIza...                           # 동일 키 재사용
GEMINI_DEEP_RESEARCH_MODEL=gemini-2.0-flash-thinking-exp
GEMINI_DEEP_RESEARCH_TIMEOUT=300.0              # agentic research는 시간 소요
GEMINI_DEEP_RESEARCH_POLL_INTERVAL=5.0
GEMINI_DEEP_RESEARCH_MAX_CLAIMS=10
```

### OpenRouter 역할별 모델

```env
OPENROUTER_PLANNER_MODEL=openai/gpt-5.4
OPENROUTER_BUILDER_MODEL=anthropic/claude-sonnet-4.6
OPENROUTER_DOC_MODEL=openai/gpt-5.4-mini
OPENROUTER_REVIEWER_MODEL=openai/gpt-5.4-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_PLANNER_REASONING_EFFORT=high
OPENROUTER_BUILDER_VERBOSITY=high
```

### Support

```env
PERPLEXITY_API_KEY=pplx-...
```

## Research 어댑터 역할 요약

| 어댑터 | 키 | 역할 | 분류 |
|--------|-----|------|------|
| Gemini Deep Research | `GEMINI_API_KEY` | agentic 심층리서치 | 핵심 |
| GPT Deep Research | `OPENAI_API_KEY` | web_search 심층리서치 | 핵심 |
| Perplexity | `PERPLEXITY_API_KEY` | 웹 보강 | support |
| Gemini (grounding) | `GEMINI_API_KEY` | 빠른 검색 | support |
| YouTube | 없음 | 영상 자료 stub | fallback |

## 테스트

```bash
pytest -v   # 목표: 280 passed
```

## 다음 구간

- Cursor 자동 실행 (Background Agent API 연동)
