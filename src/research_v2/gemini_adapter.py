"""
src/research_v2/gemini_adapter.py — Google Gemini 3.1 Pro + google_search 어댑터.

벤더: Google
모델: gemini-3.1-pro-preview (기본) — 환경변수로 변경 가능
API: https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent
툴: google_search (grounding)

특징:
  - Anthropic/OpenAI와 전혀 다른 응답 구조 (candidates[0].content.parts)
  - grounding_metadata.grounding_chunks 에서 인용 URL 추출
  - usageMetadata 필드명: promptTokenCount / candidatesTokenCount

환경변수:
  GEMINI_API_KEY 또는 GOOGLE_API_KEY — 둘 중 하나
  GEMINI_RESEARCH_MODEL — 선택 (기본 gemini-3.1-pro-preview)

응답 구조:
  {
    "candidates": [{
      "content": {
        "parts": [
          {"text": "# 보고서 본문..."},
          ...
        ]
      },
      "grounding_metadata": {
        "grounding_chunks": [
          {"web": {"uri": "https://a.com", "title": "A"}},
          {"web": {"uri": "https://b.com", "title": "B"}}
        ]
      }
    }],
    "usageMetadata": {
      "promptTokenCount": 120,
      "candidatesTokenCount": 2500,
      "totalTokenCount": 2620
    }
  }

Note:
  - parts가 여러 개면 text를 이어붙임
  - google_search 툴이 인용을 grounding_chunks로 반환
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx

from src.research_v2.base import (
    ResearchAdapter,
    ResearchResult,
    ResearchCitation,
    STATUS_SUCCESS,
    STATUS_FAILED,
)


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_MODEL = "gemini-3.1-pro-preview"

# 가격 (per 1M tokens)
_INPUT_RATE_PER_M = 1.25
_OUTPUT_RATE_PER_M = 5.00


class GeminiResearchAdapter(ResearchAdapter):
    """Google Gemini + google_search 어댑터."""

    name = "gemini_grounded_research"
    default_timeout = 300.0

    # ---------------------------------------------------------------------
    # 가용성
    # ---------------------------------------------------------------------

    def is_available(self) -> bool:
        return bool(_get_api_key())

    # ---------------------------------------------------------------------
    # 본 호출
    # ---------------------------------------------------------------------

    def _do_research(self, query: str, timeout: float) -> ResearchResult:
        api_key = _get_api_key()
        model = os.environ.get("GEMINI_RESEARCH_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL

        url = f"{_API_BASE}/{model}:generateContent"

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": query}],
                }
            ],
            "tools": [{"google_search": {}}],
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "You are an expert research assistant. "
                            "Use Google Search to gather information and provide "
                            "a comprehensive, well-structured markdown report "
                            "with clear sections and cited sources."
                        )
                    }
                ]
            },
        }

        response = httpx.post(
            url,
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )

        # HTTP 에러
        if response.status_code >= 400:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"HTTP {response.status_code}: {response.text[:200]}",
            )

        body = response.json()
        return self._parse_response(body, model)

    # ---------------------------------------------------------------------
    # 응답 파싱
    # ---------------------------------------------------------------------

    def _parse_response(self, body: Dict[str, Any], model: str) -> ResearchResult:
        """Gemini generateContent 응답 → ResearchResult."""
        # candidates 추출
        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            # 응답이 빈 경우나 blocked (promptFeedback) 처리
            block_reason = body.get("promptFeedback", {}).get("blockReason")
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"no candidates (block_reason={block_reason})" if block_reason else "no candidates",
                raw_meta={"body_keys": list(body.keys()) if isinstance(body, dict) else []},
            )

        candidate = candidates[0]
        if not isinstance(candidate, dict):
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error="candidate[0] is not a dict",
            )

        # 보고서 텍스트 추출 (parts 여러 개 이어붙이기)
        report = _extract_text_from_parts(candidate.get("content"))

        if not report:
            # finishReason 체크 (SAFETY / RECITATION 등)
            finish = candidate.get("finishReason", "")
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"empty report (finishReason={finish})" if finish else "empty report",
                raw_meta={"finish_reason": finish},
            )

        # grounding_chunks 에서 인용 추출
        citations = _extract_grounding_citations(candidate.get("grounding_metadata"))

        # 비용 계산
        usage = body.get("usageMetadata") or {}
        cost = _calculate_cost(usage)

        return ResearchResult(
            adapter_name=self.name,
            status=STATUS_SUCCESS,
            report=report,
            citations=citations,
            model=model,
            cost_usd=cost,
            raw_meta={"usage": usage},
        )


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """GEMINI_API_KEY 또는 GOOGLE_API_KEY 중 먼저 발견된 것."""
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        key = os.environ.get(var, "").strip()
        if key:
            return key
    return ""


def _extract_text_from_parts(content: Any) -> str:
    """
    candidate.content.parts 배열에서 모든 text를 이어붙임.

    구조:
      {"parts": [{"text": "..."}, {"text": "..."}]}
    """
    if not isinstance(content, dict):
        return ""

    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""

    texts = []
    for part in parts:
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str) and text:
                texts.append(text)

    return "".join(texts)


def _extract_grounding_citations(grounding_metadata: Any) -> List[ResearchCitation]:
    """
    grounding_metadata.grounding_chunks 에서 웹 인용만 추출.

    구조:
      {
        "grounding_chunks": [
          {"web": {"uri": "https://...", "title": "..."}},
          {"retrievedContext": {...}}  # ← 이건 제외
        ]
      }

    web 필드가 있는 chunk만 대상.
    """
    if not isinstance(grounding_metadata, dict):
        return []

    chunks = grounding_metadata.get("grounding_chunks")
    if not isinstance(chunks, list):
        return []

    result: List[ResearchCitation] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        web = chunk.get("web")
        if not isinstance(web, dict):
            continue
        uri = str(web.get("uri") or "").strip()
        if not uri:
            continue
        result.append(ResearchCitation(
            url=uri,
            title=str(web.get("title", "")),
            snippet=str(web.get("snippet", "")),
        ))
    return result


def _calculate_cost(usage: Dict[str, Any]) -> float:
    """
    Gemini usageMetadata 기반 비용 계산.

    필드명: promptTokenCount, candidatesTokenCount (camelCase)
    """
    if not isinstance(usage, dict):
        return 0.0

    def _safe_int(val) -> int:
        try:
            return max(0, int(val or 0))
        except (TypeError, ValueError):
            return 0

    input_tokens = _safe_int(usage.get("promptTokenCount"))
    output_tokens = _safe_int(usage.get("candidatesTokenCount"))

    cost = (
        (input_tokens * _INPUT_RATE_PER_M) / 1_000_000.0
        + (output_tokens * _OUTPUT_RATE_PER_M) / 1_000_000.0
    )
    return round(cost, 6)
