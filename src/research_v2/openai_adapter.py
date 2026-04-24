"""
src/research_v2/openai_adapter.py — OpenAI GPT-5.4 + web_search 어댑터.

벤더: OpenAI
모델: gpt-5.4 (기본) — 환경변수로 변경 가능
API: https://api.openai.com/v1/responses (Responses API)
툴: web_search_preview

특징:
  - Chat Completions 아닌 Responses API 사용
  - Deep Research 전용 모델 대신 일반 모델 + 웹검색 (폴링 불필요)
  - 타임아웃 300초 (동기)
  - citations는 message content의 annotations에서 추출

환경변수:
  OPENAI_API_KEY           — 필수
  OPENAI_RESEARCH_MODEL    — 선택 (기본 gpt-5.4)

Responses API 응답 구조:
  {
    "id": "resp_xxx",
    "status": "completed" | "failed" | "in_progress" | ...,
    "output": [
      {"type": "web_search_call", ...},
      {
        "type": "message",
        "content": [{
          "type": "output_text",
          "text": "보고서 본문",
          "annotations": [
            {"type": "url_citation", "url": "...", "title": "..."}
          ]
        }]
      }
    ],
    "usage": {"input_tokens": 120, "output_tokens": 2500}
  }

Note: Responses API는 비동기 처리를 지원하지만, 이 어댑터는 동기 mode로만 호출.
timeout 안에 완료되지 않으면 httpx 타임아웃 예외 발생.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

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

_API_URL = "https://api.openai.com/v1/responses"
_DEFAULT_MODEL = "gpt-5.4"

# 가격 (per 1M tokens) — gpt-5.4 기준
# (실제 환경 모델에 맞게 model_pricing.py가 덮어쓰기 하도록 위임)
_INPUT_RATE_PER_M = 2.50
_OUTPUT_RATE_PER_M = 15.00


class OpenAIResearchAdapter(ResearchAdapter):
    """OpenAI GPT-5.4 + web_search_preview 어댑터."""

    name = "openai_gpt_research"
    default_timeout = 300.0  # 동기 모드, 일반 모델이라 폴링 없이 완료

    # ---------------------------------------------------------------------
    # 가용성
    # ---------------------------------------------------------------------

    def is_available(self) -> bool:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        return bool(key)

    # ---------------------------------------------------------------------
    # 본 호출
    # ---------------------------------------------------------------------

    def _do_research(self, query: str, timeout: float) -> ResearchResult:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        model = os.environ.get("OPENAI_RESEARCH_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL

        # Responses API 페이로드
        payload = {
            "model": model,
            "input": [
                {
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are an expert research assistant. "
                                "Provide a comprehensive, well-structured markdown report "
                                "with clear sections, headings, and cited sources. "
                                "Use web_search to gather information from multiple sources."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": query}],
                },
            ],
            "tools": [{"type": "web_search_preview"}],
        }

        response = httpx.post(
            _API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
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
        """Responses API 응답 → ResearchResult."""
        # 상태 체크
        status = body.get("status", "")
        if status and status not in ("completed", "in_progress"):
            # "failed", "cancelled", "incomplete" 등
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"response status: {status}",
                raw_meta={"body_status": status},
            )

        # message 찾기 (output 배열 중 type=message 마지막)
        report, citations = _extract_message_content(body.get("output"))

        if not report:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error="no message content in output",
                raw_meta={"output_types": _list_output_types(body.get("output"))},
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
            raw_meta={"usage": usage, "response_id": body.get("id", "")},
        )


# ---------------------------------------------------------------------------
# 헬퍼 (모듈 레벨 — 테스트 용이)
# ---------------------------------------------------------------------------

def _extract_message_content(output: Any) -> tuple[str, List[ResearchCitation]]:
    """
    Responses API의 output 배열에서 최종 message를 찾아 텍스트·인용 추출.

    - output은 list[dict]
    - 항목 중 type == "message" 인 것의 content[0].text 가 보고서
    - content[0].annotations 의 url_citation이 인용
    - 여러 message 있으면 마지막 것 사용 (일반적으론 1개)
    """
    if not isinstance(output, list):
        return "", []

    message_item = None
    for item in output:
        if isinstance(item, dict) and item.get("type") == "message":
            message_item = item  # 마지막이 남음

    if not message_item:
        return "", []

    content = message_item.get("content")
    if not isinstance(content, list) or not content:
        return "", []

    first = content[0]
    if not isinstance(first, dict):
        return "", []

    text = str(first.get("text") or "")
    annotations = first.get("annotations") or []
    citations = _parse_annotations(annotations)

    return text, citations


def _parse_annotations(annotations: Any) -> List[ResearchCitation]:
    """
    Responses API annotations에서 url_citation만 추출.

    annotation 예시:
      {"type": "url_citation", "url": "https://...", "title": "...",
       "start_index": 100, "end_index": 200}
    """
    if not isinstance(annotations, list):
        return []

    result: List[ResearchCitation] = []
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        if ann.get("type") != "url_citation":
            continue
        url = str(ann.get("url") or "").strip()
        if not url:
            continue
        result.append(ResearchCitation(
            url=url,
            title=str(ann.get("title", "")),
            snippet=str(ann.get("snippet", "")),
        ))
    return result


def _list_output_types(output: Any) -> list:
    """디버깅용 — output 배열의 type들만 추출."""
    if not isinstance(output, list):
        return []
    return [
        item.get("type") if isinstance(item, dict) else str(type(item).__name__)
        for item in output
    ]


def _calculate_cost(usage: Dict[str, Any]) -> float:
    """
    OpenAI Responses API usage 기반 비용 계산.

    필드명: input_tokens, output_tokens (prompt_tokens 아님!)

    gpt-5.4 기준: $2.50/1M input, $15/1M output
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
