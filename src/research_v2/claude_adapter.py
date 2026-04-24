"""
src/research_v2/claude_adapter.py — Anthropic Claude + web_search 어댑터.

벤더: Anthropic
모델: claude-sonnet-4-6 (기본) — 환경변수로 변경 가능
API: https://api.anthropic.com/v1/messages
툴: web_search_20250305

특징:
  - Messages API 사용
  - content 배열이 여러 type (text / server_tool_use / web_search_tool_result) 섞임
  - text 블록들 이어붙여 report 생성
  - web_search_tool_result 블록의 content에서 인용 추출
  - 대표 모델: Sonnet 4.6 (4-AI 구성에서 Claude 몫은 Opus까지 안 가도 됨)

환경변수:
  ANTHROPIC_API_KEY        — 필수
  CLAUDE_RESEARCH_MODEL    — 선택 (기본 claude-sonnet-4-6)

응답 구조:
  {
    "id": "msg_xxx",
    "role": "assistant",
    "content": [
      {"type": "text", "text": "first part..."},
      {"type": "server_tool_use", "name": "web_search", "input": {...}},
      {"type": "web_search_tool_result", "content": [
        {"url": "https://...", "title": "...", "encrypted_content": "..."}
      ]},
      {"type": "text", "text": "final report..."}
    ],
    "usage": {"input_tokens": 120, "output_tokens": 2500}
  }
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

_API_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "claude-sonnet-4-6"
_ANTHROPIC_VERSION = "2023-06-01"

# 기본 max_tokens (응답 최대 길이)
_MAX_TOKENS = 4096

# 가격 (per 1M tokens) — Sonnet 4.6 기준
_INPUT_RATE_PER_M = 3.00
_OUTPUT_RATE_PER_M = 15.00


class ClaudeResearchAdapter(ResearchAdapter):
    """Anthropic Claude + web_search 어댑터."""

    name = "claude_web_research"
    default_timeout = 300.0

    # ---------------------------------------------------------------------
    # 가용성
    # ---------------------------------------------------------------------

    def is_available(self) -> bool:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        return bool(key)

    # ---------------------------------------------------------------------
    # 본 호출
    # ---------------------------------------------------------------------

    def _do_research(self, query: str, timeout: float) -> ResearchResult:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        model = os.environ.get("CLAUDE_RESEARCH_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL

        payload = {
            "model": model,
            "max_tokens": _MAX_TOKENS,
            "system": (
                "You are an expert research assistant. "
                "Use the web_search tool to gather information from multiple authoritative sources. "
                "Provide a comprehensive, well-structured markdown report "
                "with clear sections, headings, and cited sources."
            ),
            "messages": [
                {"role": "user", "content": query},
            ],
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 5,
                }
            ],
        }

        response = httpx.post(
            _API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
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
        """Messages API 응답 → ResearchResult."""
        # stop_reason 체크
        stop_reason = body.get("stop_reason", "")
        if stop_reason == "error" or body.get("type") == "error":
            err_msg = str(body.get("error", {}).get("message", "unknown error"))
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"API error: {err_msg}",
                raw_meta={"stop_reason": stop_reason},
            )

        content = body.get("content")
        if not isinstance(content, list) or not content:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error="no content array in response",
                raw_meta={"body_keys": list(body.keys()) if isinstance(body, dict) else []},
            )

        # text 블록 이어붙이기
        report = _extract_text_blocks(content)

        # web_search_tool_result 에서 citations 추출
        citations = _extract_web_search_citations(content)

        if not report:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"empty report (stop_reason={stop_reason})" if stop_reason else "empty report",
                raw_meta={"stop_reason": stop_reason},
            )

        # 비용 계산
        usage = body.get("usage") or {}
        cost = _calculate_cost(usage)

        return ResearchResult(
            adapter_name=self.name,
            status=STATUS_SUCCESS,
            report=report,
            citations=citations,
            model=model,
            cost_usd=cost,
            raw_meta={
                "usage": usage,
                "stop_reason": stop_reason,
                "message_id": body.get("id", ""),
            },
        )


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _extract_text_blocks(content: Any) -> str:
    """
    content 배열에서 type="text" 블록들의 text를 순서대로 이어붙임.

    다른 타입 (server_tool_use, web_search_tool_result, thinking 등)은 제외.
    중간에 여러 text 블록이 있어도 자연스럽게 연결 (구분자 2개 줄바꿈).
    """
    if not isinstance(content, list):
        return ""

    texts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text)

    return "\n\n".join(texts)


def _extract_web_search_citations(content: Any) -> List[ResearchCitation]:
    """
    content 배열의 web_search_tool_result 블록에서 인용 추출.

    구조:
      {
        "type": "web_search_tool_result",
        "content": [
          {
            "type": "web_search_result",
            "url": "https://...",
            "title": "...",
            "encrypted_content": "..."
          }
        ]
      }

    중복 URL은 한 번만 포함.
    """
    if not isinstance(content, list):
        return []

    seen_urls = set()
    result: List[ResearchCitation] = []

    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "web_search_tool_result":
            continue

        inner_content = block.get("content")
        if not isinstance(inner_content, list):
            continue

        for item in inner_content:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            result.append(ResearchCitation(
                url=url,
                title=str(item.get("title", "")),
                snippet=str(item.get("snippet", "")),
            ))

    return result


def _calculate_cost(usage: Dict[str, Any]) -> float:
    """
    Anthropic Messages API usage 기반 비용 계산.

    필드명: input_tokens, output_tokens
    (cache_read_input_tokens, cache_creation_input_tokens도 있을 수 있지만 단순화)
    """
    if not isinstance(usage, dict):
        return 0.0

    def _safe_int(val) -> int:
        try:
            return max(0, int(val or 0))
        except (TypeError, ValueError):
            return 0

    input_tokens = _safe_int(usage.get("input_tokens"))
    output_tokens = _safe_int(usage.get("output_tokens"))

    cost = (
        (input_tokens * _INPUT_RATE_PER_M) / 1_000_000.0
        + (output_tokens * _OUTPUT_RATE_PER_M) / 1_000_000.0
    )
    return round(cost, 6)
