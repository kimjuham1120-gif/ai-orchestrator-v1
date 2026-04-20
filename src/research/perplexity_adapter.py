"""
Perplexity Research Adapter — Perplexity AI Sonar API 기반.

Day 41: deferred stub → real 연결.

특징:
  - Perplexity /chat/completions endpoint (OpenAI 호환 형식)
  - httpx 사용 (동기)
  - 모델명 / endpoint env override 가능
  - BaseResearchAdapter 계약 준수

환경변수:
  PERPLEXITY_API_KEY        — 필수. 없으면 is_available()=False (비활성)
  PERPLEXITY_MODEL          — 기본값: sonar
  PERPLEXITY_BASE_URL       — 기본값: https://api.perplexity.ai
  PERPLEXITY_TIMEOUT        — 초 단위 float, 기본값: 30.0

동작 규칙:
  key 없음          → is_available()=False, search() 호출 불가
  key 있음 + 성공   → real claims 반환
  key 있음 + 실패   → 예외 전파 (조용한 폴백 금지)
"""
from __future__ import annotations

import os
from typing import Optional

from src.research.base import BaseResearchAdapter, ResearchClaim, ResearchResult

_DEFAULT_MODEL = "sonar"
_DEFAULT_BASE_URL = "https://api.perplexity.ai"
_DEFAULT_TIMEOUT = 30.0

_RESEARCH_SYSTEM = (
    "You are a software research assistant. "
    "Return concise, factual findings relevant to software development. "
    "Format each finding as: finding text | source type "
    "(source type: official-docs / tech-blog / community / general-web). "
    "Separate findings with newlines. Maximum 5 findings."
)

_RESEARCH_USER_TMPL = "Research the following topic from a software development perspective:\n\n{query}"


class PerplexityAdapter(BaseResearchAdapter):
    name = "perplexity"

    def __init__(self) -> None:
        self._api_key: Optional[str] = os.environ.get("PERPLEXITY_API_KEY")
        self._model: str = os.environ.get("PERPLEXITY_MODEL", _DEFAULT_MODEL)
        self._base_url: str = os.environ.get(
            "PERPLEXITY_BASE_URL", _DEFAULT_BASE_URL
        ).rstrip("/")
        self._timeout: float = float(
            os.environ.get("PERPLEXITY_TIMEOUT", _DEFAULT_TIMEOUT)
        )

    def is_available(self) -> bool:
        return bool(self._api_key)

    def search(self, query: str) -> ResearchResult:
        """
        key 없으면 호출하지 않는다 (router가 is_available 확인 후 호출).
        key 있고 실패 시 예외 전파.
        """
        if not self.is_available():
            # 방어 코드 — router가 is_available 체크하지만 직접 호출 대비
            return ResearchResult(
                adapter_name=self.name,
                error="PERPLEXITY_API_KEY not set",
            )

        import httpx

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _RESEARCH_SYSTEM},
                {"role": "user", "content": _RESEARCH_USER_TMPL.format(query=query)},
            ],
        }

        # 예외(httpx.HTTPError, timeout 등)는 그대로 전파
        response = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=self._timeout,
        )
        response.raise_for_status()  # 4xx/5xx → httpx.HTTPStatusError 전파

        data = response.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        if not content:
            return ResearchResult(
                adapter_name=self.name,
                error="Perplexity 응답이 비어있음",
            )

        claims = _parse_claims(content, query)
        return ResearchResult(adapter_name=self.name, claims=claims)


def _parse_claims(text: str, query: str) -> list[ResearchClaim]:
    """
    "finding text | source type" 형식 파싱.
    파싱 실패 시 줄 단위 폴백.
    """
    claims: list[ResearchClaim] = []
    for line in text.splitlines():
        line = line.strip()
        # 번호 접두어 제거
        if line and line[0].isdigit() and ". " in line:
            line = line.split(". ", 1)[1].strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if not line:
            continue

        if "|" in line:
            parts = line.split("|", 1)
            text_part = parts[0].strip()
            source_part = parts[1].strip() if len(parts) > 1 else "perplexity"
        else:
            text_part = line
            source_part = "perplexity/sonar"

        if text_part:
            claims.append(ResearchClaim(text=text_part, source=source_part))

    if not claims:
        claims = [ResearchClaim(text=text, source=f"perplexity/{query[:30]}")]

    return claims
