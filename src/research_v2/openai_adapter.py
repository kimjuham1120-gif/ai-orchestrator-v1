"""
src/research_v2/openai_adapter.py — OpenAI 어댑터 (듀얼 모드).

벤더: OpenAI
API: https://api.openai.com/v1/responses (Responses API)

모드:
  - "web_search"    (기본): gpt-5.4 + web_search_preview, 동기 호출 (~5분)
  - "deep_research":        o4-mini-deep-research-2025-06-26
                            + background=true + 폴링 (최대 20분)

환경변수:
  OPENAI_API_KEY                   — 필수
  OPENAI_RESEARCH_MODEL            — web_search 모드 모델 오버라이드 (기본 gpt-5.4)
  OPENAI_DEEP_RESEARCH_MODEL       — deep_research 모델 오버라이드 (기본 o4-mini-deep-research-2025-06-26)

Deep Research 응답 상태:
  - queued, in_progress            → 폴링 계속
  - completed                      → 결과 파싱
  - failed, cancelled, incomplete  → 실패

가격:
  gpt-5.4:                 $2.50/1M input, $15.00/1M output
  o4-mini-deep-research:   $2.00/1M input, $8.00/1M output
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Tuple

import httpx

from src.research_v2.base import (
    ResearchAdapter,
    ResearchResult,
    ResearchCitation,
    STATUS_SUCCESS,
    STATUS_FAILED,
)


# ---------------------------------------------------------------------------
# 모드 상수
# ---------------------------------------------------------------------------

MODE_WEB_SEARCH = "web_search"
MODE_DEEP_RESEARCH = "deep_research"
_VALID_MODES = {MODE_WEB_SEARCH, MODE_DEEP_RESEARCH}

# Responses API 엔드포인트
_API_URL = "https://api.openai.com/v1/responses"

# 기본 모델
_DEFAULT_WEB_SEARCH_MODEL = "gpt-5.4"
_DEFAULT_DR_MODEL = "o4-mini-deep-research-2025-06-26"

# Deep Research 폴링 설정
_DR_POLL_INTERVAL_SEC = 15.0   # 폴링 간격
_DR_MAX_WAIT_SEC = 1200.0      # 최대 대기 (20분)
_DR_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "incomplete"}
_DR_POLLING_STATUSES = {"queued", "in_progress"}

# 모드별 설정
_MODE_CONFIG = {
    MODE_WEB_SEARCH: {
        "env_var": "OPENAI_RESEARCH_MODEL",
        "default_model": _DEFAULT_WEB_SEARCH_MODEL,
        "timeout": 300.0,
        "input_rate_per_m": 2.50,
        "output_rate_per_m": 15.00,
        "uses_background": False,
    },
    MODE_DEEP_RESEARCH: {
        "env_var": "OPENAI_DEEP_RESEARCH_MODEL",
        "default_model": _DEFAULT_DR_MODEL,
        "timeout": _DR_MAX_WAIT_SEC,
        "input_rate_per_m": 2.00,
        "output_rate_per_m": 8.00,
        "uses_background": True,
    },
}


class OpenAIResearchAdapter(ResearchAdapter):
    """OpenAI 어댑터 — web_search 또는 deep_research 모드."""

    name = "openai_research"

    def __init__(
        self,
        mode: str = MODE_WEB_SEARCH,
        poll_interval: float = _DR_POLL_INTERVAL_SEC,
        max_wait: float = _DR_MAX_WAIT_SEC,
    ):
        if mode not in _VALID_MODES:
            raise ValueError(
                f"invalid mode '{mode}'. must be one of {sorted(_VALID_MODES)}"
            )
        self.mode = mode
        self._config = _MODE_CONFIG[mode]
        self.poll_interval = poll_interval
        self.max_wait = max_wait

    @property
    def default_timeout(self) -> float:
        return self._config["timeout"]

    # ---------------------------------------------------------------------
    # 가용성
    # ---------------------------------------------------------------------

    def is_available(self) -> bool:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        return bool(key)

    # ---------------------------------------------------------------------
    # 본 호출 — 모드 분기
    # ---------------------------------------------------------------------

    def _do_research(self, query: str, timeout: float) -> ResearchResult:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        model = _resolve_model(self._config)

        if self._config["uses_background"]:
            return self._do_deep_research(api_key, model, query, timeout)
        return self._do_web_search(api_key, model, query, timeout)

    # ---------------------------------------------------------------------
    # web_search 모드 (동기)
    # ---------------------------------------------------------------------

    def _do_web_search(
        self, api_key: str, model: str, query: str, timeout: float
    ) -> ResearchResult:
        payload = _build_payload(model, query, background=False)

        response = httpx.post(
            _API_URL,
            headers=_build_headers(api_key),
            json=payload,
            timeout=timeout,
        )

        if response.status_code >= 400:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"HTTP {response.status_code}: {response.text[:200]}",
            )

        body = response.json()
        return self._parse_final_response(body, model)

    # ---------------------------------------------------------------------
    # deep_research 모드 (비동기 + 폴링)
    # ---------------------------------------------------------------------

    def _do_deep_research(
        self, api_key: str, model: str, query: str, timeout: float
    ) -> ResearchResult:
        # 1. 요청 시작 (background=true)
        submit_result = self._submit_deep_research(api_key, model, query)
        if submit_result["error"]:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=submit_result["error"],
            )

        response_id = submit_result["response_id"]

        # 2. 폴링 루프
        final_body = self._poll_until_complete(api_key, response_id, timeout)

        if final_body is None:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"polling timeout after {timeout}s",
                raw_meta={"response_id": response_id},
            )

        # 3. 최종 상태 체크
        status = final_body.get("status", "")
        if status != "completed":
            err_msg = _extract_error_message(final_body)
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"response status: {status}"
                + (f" ({err_msg})" if err_msg else ""),
                raw_meta={"response_id": response_id, "status": status},
            )

        # 4. 결과 파싱
        return self._parse_final_response(final_body, model)

    # ---------------------------------------------------------------------
    # Deep Research: 요청 시작
    # ---------------------------------------------------------------------

    def _submit_deep_research(
        self, api_key: str, model: str, query: str
    ) -> Dict[str, Any]:
        """
        POST /v1/responses (background=true) → response_id 획득.

        Returns:
          {"response_id": str | None, "error": str | None}
        """
        payload = _build_payload(model, query, background=True)

        try:
            resp = httpx.post(
                _API_URL,
                headers=_build_headers(api_key),
                json=payload,
                timeout=30.0,  # submit은 빨라야 함
            )
        except httpx.TimeoutException as e:
            return {"response_id": None, "error": f"submit timeout: {e}"}
        except httpx.HTTPError as e:
            return {"response_id": None, "error": f"submit error: {e}"}

        if resp.status_code >= 400:
            return {
                "response_id": None,
                "error": f"submit HTTP {resp.status_code}: {resp.text[:200]}",
            }

        body = resp.json()
        response_id = str(body.get("id") or "").strip()
        if not response_id:
            return {"response_id": None, "error": "submit response missing 'id'"}

        return {"response_id": response_id, "error": None}

    # ---------------------------------------------------------------------
    # Deep Research: 폴링 루프
    # ---------------------------------------------------------------------

    def _poll_until_complete(
        self, api_key: str, response_id: str, timeout: float
    ) -> Dict[str, Any] | None:
        """
        GET /v1/responses/{id} 를 poll_interval 간격으로 반복.

        Returns:
          최종 body (completed/failed/cancelled 중 하나) 또는 None (타임아웃).
        """
        max_wait = min(timeout, self.max_wait)
        elapsed = 0.0
        poll_url = f"{_API_URL}/{response_id}"
        headers = _build_headers(api_key)

        while elapsed < max_wait:
            time.sleep(self.poll_interval)
            elapsed += self.poll_interval

            try:
                resp = httpx.get(poll_url, headers=headers, timeout=30.0)
            except httpx.HTTPError:
                # 일시적 네트워크 오류 → 다음 폴링 시도
                continue

            if resp.status_code >= 400:
                # 4xx/5xx → 다음 폴링 시도 (일시적일 수 있음)
                continue

            try:
                body = resp.json()
            except Exception:
                continue

            status = body.get("status", "")
            if status in _DR_TERMINAL_STATUSES:
                return body
            # queued / in_progress → 계속 폴링

        return None  # 타임아웃

    # ---------------------------------------------------------------------
    # 최종 응답 파싱 (web_search / deep_research 공통)
    # ---------------------------------------------------------------------

    def _parse_final_response(
        self, body: Dict[str, Any], model: str
    ) -> ResearchResult:
        """Responses API 최종 응답 → ResearchResult."""
        # web_search 모드에서는 status 없을 수 있음 (동기)
        status = body.get("status", "")
        if status and status not in ("completed", "in_progress"):
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"response status: {status}",
                raw_meta={"body_status": status},
            )

        report, citations = _extract_message_content(body.get("output"))

        if not report:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error="no message content in output",
                raw_meta={"output_types": _list_output_types(body.get("output"))},
            )

        usage = body.get("usage") or {}
        cost = _calculate_cost(usage, self._config)

        return ResearchResult(
            adapter_name=self.name,
            status=STATUS_SUCCESS,
            report=report,
            citations=citations,
            model=model,
            cost_usd=cost,
            raw_meta={
                "usage": usage,
                "response_id": body.get("id", ""),
                "mode": self.mode,
            },
        )


# ---------------------------------------------------------------------------
# 헬퍼 — 페이로드 / 헤더 / 모델 해석
# ---------------------------------------------------------------------------

def _build_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _build_payload(model: str, query: str, background: bool) -> Dict[str, Any]:
    """Responses API 공통 페이로드 (web_search + deep_research 공유)."""
    payload: Dict[str, Any] = {
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
    if background:
        payload["background"] = True
    return payload


def _resolve_model(config: Dict[str, Any]) -> str:
    """환경변수 → 기본값 순서로 모델 결정."""
    env_var = config["env_var"]
    default = config["default_model"]
    return (os.environ.get(env_var, "").strip() or default)


# ---------------------------------------------------------------------------
# 헬퍼 — 응답 파싱
# ---------------------------------------------------------------------------

def _extract_message_content(output: Any) -> Tuple[str, List[ResearchCitation]]:
    """output 배열에서 type=message 블록의 텍스트 + annotations 추출."""
    if not isinstance(output, list):
        return "", []

    message_item = None
    for item in output:
        if isinstance(item, dict) and item.get("type") == "message":
            message_item = item  # 마지막이 최종

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
    """url_citation 타입만 추출."""
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
    if not isinstance(output, list):
        return []
    return [
        item.get("type") if isinstance(item, dict) else str(type(item).__name__)
        for item in output
    ]


def _extract_error_message(body: Dict[str, Any]) -> str:
    """failed/cancelled 응답에서 에러 메시지 추출."""
    err = body.get("error")
    if isinstance(err, dict):
        msg = err.get("message")
        if msg:
            return str(msg)
    incomplete = body.get("incomplete_details")
    if isinstance(incomplete, dict):
        reason = incomplete.get("reason")
        if reason:
            return str(reason)
    return ""


# ---------------------------------------------------------------------------
# 헬퍼 — 비용 계산 (모드별 단가)
# ---------------------------------------------------------------------------

def _calculate_cost(usage: Dict[str, Any], config: Dict[str, Any]) -> float:
    """Responses API usage 기반 비용 계산. 필드명: input_tokens/output_tokens."""
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
        (input_tokens * config["input_rate_per_m"]) / 1_000_000.0
        + (output_tokens * config["output_rate_per_m"]) / 1_000_000.0
    )
    return round(cost, 6)
