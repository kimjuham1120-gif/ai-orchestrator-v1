"""
GPT Deep Research Adapter — OpenAI Responses API 기반.

Day 49 도입 → Day 65 보강: 심층리서치 품질 강화.

특징:
  - OpenAI Responses API (/v1/responses) + web_search_preview 툴
  - o4-mini-deep-research / gpt-4o 등 deep research 전용 모델 지원
  - 프롬프트를 심층리서치 목적에 최적화 (단순 검색 → 구조화 분석)
  - claim 품질 강화: 근거 + 출처 + 신뢰도 레벨 추출
  - httpx 사용 (동기, openai SDK 미의존)
  - BaseResearchAdapter 계약 준수

환경변수:
  OPENAI_API_KEY          — 필수. 없으면 is_available()=False
  GPT_RESEARCH_MODEL      — 기본값: gpt-4o-mini
                            심층리서치 권장: openai/o4-mini-deep-research (OpenRouter 경유)
                            또는: gpt-4o (OpenAI 직결)
  GPT_RESEARCH_BASE_URL   — 기본값: https://api.openai.com/v1
  GPT_RESEARCH_TIMEOUT    — 초 단위 float, 기본값: 120.0 (deep research는 시간 소요)
  GPT_RESEARCH_MAX_TOKENS — 기본값: 2000 (심층리서치 결과는 길어질 수 있음)

동작 규칙:
  key 없음          → is_available()=False
  key 있음 + 성공   → real claims 반환
  key 있음 + 실패   → 예외 전파 (silent fallback 금지)

역할:
  광범위 웹 탐색 + 추론 기반 심층분석 → 구조화된 EvidenceBundle 생성
"""
from __future__ import annotations

import os
from typing import Optional

from src.research.base import BaseResearchAdapter, ResearchClaim, ResearchResult

_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_TIMEOUT = 120.0   # deep research는 시간 소요
_DEFAULT_MAX_TOKENS = 2000

# 심층리서치 전용 프롬프트 — 단순 검색이 아닌 구조화 분석
_DEEP_RESEARCH_PROMPT = """\
You are an expert software research analyst conducting deep research.

Research topic: {query}

Your task:
1. Search for authoritative information about this topic
2. Analyze and synthesize findings from multiple angles
3. Focus on: technical accuracy, practical applicability, recent developments

Return your findings in this exact format (one finding per line):
[finding text] | [source type] | [confidence: high/medium/low]

Source types: official-docs / tech-blog / community / research-paper / general-web

Requirements:
- Maximum 8 findings
- Each finding must be specific and actionable
- Prioritize official documentation and well-known technical sources
- Include recent developments if relevant
- findings should be in the same language as the query
"""


class GPTResearchAdapter(BaseResearchAdapter):
    name = "gpt_research"

    def __init__(self) -> None:
        self._api_key: Optional[str] = os.environ.get("OPENAI_API_KEY")
        self._model: str = os.environ.get("GPT_RESEARCH_MODEL", _DEFAULT_MODEL)
        self._base_url: str = os.environ.get(
            "GPT_RESEARCH_BASE_URL", _DEFAULT_BASE_URL
        ).rstrip("/")
        self._timeout: float = float(
            os.environ.get("GPT_RESEARCH_TIMEOUT", _DEFAULT_TIMEOUT)
        )
        self._max_tokens: int = int(
            os.environ.get("GPT_RESEARCH_MAX_TOKENS", _DEFAULT_MAX_TOKENS)
        )

    def is_available(self) -> bool:
        return bool(self._api_key)

    def search(self, query: str) -> ResearchResult:
        if not self.is_available():
            return ResearchResult(
                adapter_name=self.name,
                error="OPENAI_API_KEY not set",
            )

        import httpx

        url = f"{self._base_url}/responses"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "tools": [{"type": "web_search_preview"}],
            "input": _DEEP_RESEARCH_PROMPT.format(query=query),
            "max_output_tokens": self._max_tokens,
        }

        response = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=self._timeout,
        )
        response.raise_for_status()

        data = response.json()
        content = _extract_content(data)

        if not content:
            return ResearchResult(
                adapter_name=self.name,
                error="GPT deep research 응답이 비어있음",
            )

        claims = _parse_deep_research_claims(content, query)
        return ResearchResult(adapter_name=self.name, claims=claims)


def _extract_content(data: dict) -> str:
    """Responses API 응답에서 텍스트 추출. choices 형식도 지원."""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    return part.get("text", "").strip()
    # fallback: choices 형식
    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "").strip()
    return ""


def _parse_deep_research_claims(text: str, query: str) -> list[ResearchClaim]:
    """
    심층리서치 결과 파싱.
    형식: "finding text | source type | confidence: high/medium/low"
    또는 기존: "finding text | source type"
    파싱 실패 시 줄 단위 폴백.
    """
    claims: list[ResearchClaim] = []

    for line in text.splitlines():
        line = line.strip()
        # 번호/bullet 접두어 제거
        if line and line[0].isdigit() and ". " in line:
            line = line.split(". ", 1)[1].strip()
        if line.startswith(("- ", "* ", "• ")):
            line = line[2:].strip()
        if not line:
            continue

        parts = [p.strip() for p in line.split("|")]

        if len(parts) >= 3:
            # "finding | source | confidence" 형식
            text_part = parts[0]
            source_part = parts[1]
            confidence_raw = parts[2].lower()
            # confidence를 source에 태깅
            confidence = "high" if "high" in confidence_raw else \
                         "low" if "low" in confidence_raw else "medium"
            source_tagged = f"{source_part}[{confidence}]"
        elif len(parts) == 2:
            text_part = parts[0]
            source_tagged = parts[1]
        else:
            text_part = line
            source_tagged = "gpt_research/web_search"

        if text_part:
            claims.append(ResearchClaim(text=text_part, source=source_tagged))

    if not claims:
        # 전체를 단일 claim으로
        claims = [ResearchClaim(text=text[:500], source=f"gpt_research/{query[:30]}")]

    return claims
