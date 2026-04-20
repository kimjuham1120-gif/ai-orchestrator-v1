"""
Gemini Research Adapter — Google AI Studio 공식 코드 기반.

업로드된 ai_studio_code.py를 BaseResearchAdapter 계약에 맞게 통합.

특징:
  - google_search 툴 사용 → Grounding with Google Search (웹 검색 기반 리서치)
  - thinking_level="HIGH" → 검색 결과를 근거로 추론
  - 스트리밍 응답을 수집해 단일 텍스트로 합산

환경변수:
  GEMINI_API_KEY          — Google AI Studio에서 발급 (기본)
  GOOGLE_API_KEY          — 대체 키 이름. 둘 다 있으면 GOOGLE_API_KEY 우선
  GEMINI_MODEL            — 기본값: gemini-2.5-flash
  GEMINI_THINKING_LEVEL   — "HIGH" / "MEDIUM" / "LOW" (기본: HIGH)

동작 규칙 (조용한 fake 폴백 금지):
  key 없음          → ResearchResult(error=...), is_available()=False
  key 있음 + 성공   → real claims 반환
  key 있음 + 실패   → 예외 전파
"""
from __future__ import annotations

import os
from typing import Optional

from src.research.base import BaseResearchAdapter, ResearchClaim, ResearchResult

_DEFAULT_MODEL = "gemini-2.5-flash"
_THINKING_LEVELS = {"HIGH", "MEDIUM", "LOW"}

_RESEARCH_PROMPT = """\
다음 주제에 대해 소프트웨어 개발 관점에서 리서치하고 핵심 근거를 정리해줘.

주제: {query}

요구사항:
- 각 항목은 "근거 텍스트 | 출처 성격" 형식으로 작성
- 출처 성격: 공식문서 / 기술블로그 / 커뮤니티 / 일반웹
- 5개 이내로 핵심만 정리
- 각 항목은 줄바꿈으로 구분
"""


class GeminiResearchAdapter(BaseResearchAdapter):
    name = "gemini"

    def __init__(self) -> None:
        # GOOGLE_API_KEY 우선, 없으면 GEMINI_API_KEY
        self._api_key: Optional[str] = (
            os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        )
        self._model: str = os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)
        level = os.environ.get("GEMINI_THINKING_LEVEL", "HIGH").upper()
        self._thinking_level = level if level in _THINKING_LEVELS else "HIGH"

    def is_available(self) -> bool:
        return bool(self._api_key)

    def search(self, query: str) -> ResearchResult:
        if not self.is_available():
            return ResearchResult(
                adapter_name=self.name,
                error="GEMINI_API_KEY (또는 GOOGLE_API_KEY) not set",
            )

        # key 있음 → real 호출. 실패 시 예외 전파 (조용한 폴백 없음)
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)

        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(
                    text=_RESEARCH_PROMPT.format(query=query)
                )],
            )
        ]
        # SDK 실제 필드명: google_search (camelCase googleSearch 아님)
        # thinking_config는 pro 모델 전용 — flash에서는 사용 불가
        tools = [types.Tool(google_search=types.GoogleSearch())]
        config = types.GenerateContentConfig(tools=tools)

        # 스트리밍 응답 수집
        chunks: list[str] = []
        for chunk in client.models.generate_content_stream(
            model=self._model,
            contents=contents,
            config=config,
        ):
            if chunk.text:
                chunks.append(chunk.text)

        full_text = "".join(chunks).strip()
        if not full_text:
            return ResearchResult(
                adapter_name=self.name,
                error="Gemini 응답이 비어있음",
            )

        claims = _parse_claims(full_text, query)
        return ResearchResult(adapter_name=self.name, claims=claims)


def _parse_claims(text: str, query: str) -> list[ResearchClaim]:
    """
    응답 텍스트를 ResearchClaim 리스트로 파싱.
    "근거 텍스트 | 출처 성격" 형식 우선, 파싱 실패 시 줄 단위 폴백.
    """
    claims: list[ResearchClaim] = []
    for line in text.splitlines():
        line = line.strip()
        # 번호 접두어 제거 ("1. ", "- " 등)
        if line and line[0].isdigit() and ". " in line:
            line = line.split(". ", 1)[1].strip()
        if line.startswith("- "):
            line = line[2:].strip()

        if not line:
            continue

        if "|" in line:
            parts = line.split("|", 1)
            text_part = parts[0].strip()
            source_part = parts[1].strip() if len(parts) > 1 else "gemini"
        else:
            text_part = line
            source_part = "gemini/googleSearch"

        if text_part:
            claims.append(ResearchClaim(text=text_part, source=source_part))

    # 파싱 결과 없으면 전체 텍스트를 단일 claim으로
    if not claims:
        claims = [ResearchClaim(text=text, source=f"gemini/{query[:30]}")]

    return claims
