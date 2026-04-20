"""
Gemini Deep Research Adapter — Interactions API 기반.

Day 65 수정: generate_content → Interactions API로 교체.

공식 방식:
  client.interactions.create(
      input=...,
      agent="deep-research-pro-preview-12-2025",
      background=True,
  )
  → polling client.interactions.get(interaction_id)
  → status=="completed" → outputs[-1].text 파싱

환경변수:
  GEMINI_API_KEY                     — 필수 (기존 키 재사용 가능)
  GEMINI_DEEP_RESEARCH_AGENT         — 기본값: deep-research-pro-preview-12-2025
  GEMINI_DEEP_RESEARCH_TIMEOUT       — 최대 대기 초, 기본값: 600.0
  GEMINI_DEEP_RESEARCH_POLL_INTERVAL — polling 간격 초, 기본값: 10.0
  GEMINI_DEEP_RESEARCH_MAX_CLAIMS    — 최대 claim 수, 기본값: 10

동작 규칙:
  key 없음          → is_available()=False
  key 있음 + 성공   → real claims 반환
  key 있음 + 실패   → 예외 전파 (silent fallback 금지)
  timeout           → TimeoutError 전파

역할:
  일반 gemini_adapter.py (googleSearch grounding) 와 역할 분리:
    gemini_adapter.py              → 빠른 grounding search (support)
    gemini_deep_research_adapter.py → Interactions API 심층리서치 (핵심 축)
"""
from __future__ import annotations

import os
import time
from typing import Optional

from src.research.base import BaseResearchAdapter, ResearchClaim, ResearchResult

_DEFAULT_AGENT = "deep-research-pro-preview-12-2025"
_DEFAULT_TIMEOUT = 600.0
_DEFAULT_POLL_INTERVAL = 10.0
_DEFAULT_MAX_CLAIMS = 10

_DEEP_RESEARCH_PROMPT = """\
소프트웨어 개발 관점에서 다음 주제를 심층 조사해줘.

주제: {query}

요구사항:
- 공식 문서, 기술 블로그, 커뮤니티 등 다양한 출처 종합
- 실제 개발에 적용 가능한 구체적 근거 정리
- 최신 정보 우선
- 최대 {max_claims}개 핵심 항목

결과 형식 (각 항목을 줄바꿈으로 구분):
[근거 텍스트] | [출처 성격] | [신뢰도: 높음/중간/낮음]

출처 성격: 공식문서 / 기술블로그 / 커뮤니티 / 연구논문 / 일반웹
"""


class GeminiDeepResearchAdapter(BaseResearchAdapter):
    name = "gemini_deep_research"

    def __init__(self) -> None:
        self._api_key: Optional[str] = (
            os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        )
        self._agent: str = os.environ.get(
            "GEMINI_DEEP_RESEARCH_AGENT", _DEFAULT_AGENT
        )
        self._timeout: float = float(
            os.environ.get("GEMINI_DEEP_RESEARCH_TIMEOUT", _DEFAULT_TIMEOUT)
        )
        self._poll_interval: float = float(
            os.environ.get("GEMINI_DEEP_RESEARCH_POLL_INTERVAL", _DEFAULT_POLL_INTERVAL)
        )
        self._max_claims: int = int(
            os.environ.get("GEMINI_DEEP_RESEARCH_MAX_CLAIMS", _DEFAULT_MAX_CLAIMS)
        )

    def is_available(self) -> bool:
        return bool(self._api_key)

    def search(self, query: str) -> ResearchResult:
        if not self.is_available():
            return ResearchResult(
                adapter_name=self.name,
                error="GEMINI_API_KEY (또는 GOOGLE_API_KEY) not set",
            )

        from google import genai

        client = genai.Client(api_key=self._api_key)
        prompt = _DEEP_RESEARCH_PROMPT.format(
            query=query,
            max_claims=self._max_claims,
        )

        # Interactions API — background=True (수 분 소요 가능)
        interaction = client.interactions.create(
            input=prompt,
            agent=self._agent,
            background=True,
        )
        interaction_id = interaction.id

        # polling
        deadline = time.time() + self._timeout
        while True:
            if time.time() > deadline:
                raise TimeoutError(
                    f"Gemini Deep Research timeout ({self._timeout}s) "
                    f"— interaction_id={interaction_id}"
                )

            result = client.interactions.get(interaction_id)

            if result.status == "completed":
                content = _extract_content(result)
                if not content:
                    return ResearchResult(
                        adapter_name=self.name,
                        error="Gemini Deep Research 응답이 비어있음",
                    )
                claims = _parse_claims(content, query)
                return ResearchResult(adapter_name=self.name, claims=claims)

            elif result.status == "failed":
                error_msg = getattr(result, "error", "unknown error")
                raise RuntimeError(
                    f"Gemini Deep Research 실패: {error_msg}"
                )

            time.sleep(self._poll_interval)


def _extract_content(result) -> str:
    """Interactions API 결과에서 텍스트 추출."""
    outputs = getattr(result, "outputs", None)
    if outputs:
        last = outputs[-1]
        text = getattr(last, "text", None)
        if text:
            return text.strip()
    # fallback: output 단일 필드
    output = getattr(result, "output", None)
    if output:
        return str(output).strip()
    return ""


def _parse_claims(text: str, query: str) -> list[ResearchClaim]:
    """
    형식: "근거 텍스트 | 출처 성격 | 신뢰도"
    또는: "근거 텍스트 | 출처 성격"
    """
    claims: list[ResearchClaim] = []

    for line in text.splitlines():
        line = line.strip()
        if line and line[0].isdigit() and ". " in line:
            line = line.split(". ", 1)[1].strip()
        if line.startswith(("- ", "* ", "• ")):
            line = line[2:].strip()
        if not line:
            continue

        parts = [p.strip() for p in line.split("|")]

        if len(parts) >= 3:
            text_part = parts[0]
            source_part = parts[1]
            confidence_raw = parts[2].lower()
            confidence = "high" if "높음" in confidence_raw or "high" in confidence_raw else \
                         "low" if "낮음" in confidence_raw or "low" in confidence_raw else "medium"
            source_tagged = f"{source_part}[{confidence}]"
        elif len(parts) == 2:
            text_part = parts[0]
            source_tagged = parts[1]
        else:
            text_part = line
            source_tagged = "gemini_deep_research/interactions"

        if text_part:
            claims.append(ResearchClaim(text=text_part, source=source_tagged))

    if not claims:
        claims = [ResearchClaim(
            text=text[:500],
            source=f"gemini_deep_research/{query[:30]}"
        )]

    return claims
