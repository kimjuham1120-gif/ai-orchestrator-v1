"""
src/research_v2/gemini_adapter.py — Google Gemini 어댑터 (듀얼 모드).

벤더: Google
API:
  - web_search 모드:   https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent
  - deep_research 모드: https://generativelanguage.googleapis.com/v1beta/interactions (Interactions API)

모드:
  - "web_search"    (기본): gemini-3.1-pro-preview + google_search 툴 (동기)
  - "deep_research":        deep-research-preview-04-2026 에이전트 + background + 폴링

환경변수:
  GEMINI_API_KEY 또는 GOOGLE_API_KEY — 필수
  GEMINI_RESEARCH_MODEL          — web_search 모델 오버라이드 (기본 gemini-3.1-pro-preview)
  GEMINI_DEEP_RESEARCH_AGENT     — deep_research 에이전트 오버라이드
                                    (기본 deep-research-preview-04-2026)

Deep Research 응답 상태:
  - in_progress               → 폴링 계속 (queued 없음 — OpenAI와 다름)
  - completed                 → 결과 파싱
  - failed, cancelled         → 실패

가격:
  gemini-3.1-pro:                      $1.25/1M input, $5.00/1M output
  deep-research-preview-04-2026:       세션당 ~$1.22 (session-based, 토큰도 과금)
  deep-research-max-preview-04-2026:   세션당 ~$4.80

현재 토큰 기반으로 비용 계산 (session 단위는 usage 정보로 근사).
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

# 엔드포인트
_GENERATE_CONTENT_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

# 기본 모델/에이전트
_DEFAULT_WEB_SEARCH_MODEL = "gemini-3.1-pro-preview"
_DEFAULT_DR_AGENT = "deep-research-preview-04-2026"

# Deep Research 폴링 설정
_DR_POLL_INTERVAL_SEC = 15.0
_DR_MAX_WAIT_SEC = 1800.0  # 30분 (Gemini DR은 최대 60분까지 가능)
_DR_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_DR_POLLING_STATUSES = {"in_progress"}  # Gemini는 queued 없음

# 모드별 설정
_MODE_CONFIG = {
    MODE_WEB_SEARCH: {
        "env_var": "GEMINI_RESEARCH_MODEL",
        "default_model": _DEFAULT_WEB_SEARCH_MODEL,
        "timeout": 300.0,
        "input_rate_per_m": 1.25,
        "output_rate_per_m": 5.00,
        "uses_background": False,
    },
    MODE_DEEP_RESEARCH: {
        "env_var": "GEMINI_DEEP_RESEARCH_AGENT",
        "default_model": _DEFAULT_DR_AGENT,
        "timeout": _DR_MAX_WAIT_SEC,
        "input_rate_per_m": 1.25,
        "output_rate_per_m": 5.00,
        "uses_background": True,
    },
}


class GeminiResearchAdapter(ResearchAdapter):
    """Google Gemini 어댑터 — web_search 또는 deep_research 모드."""

    name = "gemini_research"

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
        return bool(_get_api_key())

    # ---------------------------------------------------------------------
    # 본 호출 — 모드 분기
    # ---------------------------------------------------------------------

    def _do_research(self, query: str, timeout: float) -> ResearchResult:
        api_key = _get_api_key()
        model_or_agent = _resolve_model(self._config)

        if self._config["uses_background"]:
            return self._do_deep_research(api_key, model_or_agent, query, timeout)
        return self._do_web_search(api_key, model_or_agent, query, timeout)

    # ---------------------------------------------------------------------
    # web_search 모드 — 기존 generateContent (동기)
    # ---------------------------------------------------------------------

    def _do_web_search(
        self, api_key: str, model: str, query: str, timeout: float
    ) -> ResearchResult:
        url = f"{_GENERATE_CONTENT_BASE}/{model}:generateContent"

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

        if response.status_code >= 400:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"HTTP {response.status_code}: {response.text[:200]}",
            )

        body = response.json()
        return self._parse_generate_content(body, model)

    # ---------------------------------------------------------------------
    # deep_research 모드 — Interactions API + 폴링
    # ---------------------------------------------------------------------

    def _do_deep_research(
        self, api_key: str, agent: str, query: str, timeout: float
    ) -> ResearchResult:
        # 1. Interaction 시작
        submit_result = self._submit_interaction(api_key, agent, query)
        if submit_result["error"]:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=agent,
                error=submit_result["error"],
            )

        interaction_id = submit_result["interaction_id"]

        # 2. 폴링
        final_body = self._poll_until_complete(api_key, interaction_id, timeout)

        if final_body is None:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=agent,
                error=f"polling timeout after {timeout}s",
                raw_meta={"interaction_id": interaction_id},
            )

        # 3. 최종 상태 체크
        status = final_body.get("status", "")
        if status != "completed":
            err_msg = _extract_error_message(final_body)
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=agent,
                error=f"interaction status: {status}"
                + (f" ({err_msg})" if err_msg else ""),
                raw_meta={"interaction_id": interaction_id, "status": status},
            )

        # 4. 결과 파싱
        return self._parse_interaction_result(final_body, agent, interaction_id)

    # ---------------------------------------------------------------------
    # Deep Research: Interaction 시작
    # ---------------------------------------------------------------------

    def _submit_interaction(
        self, api_key: str, agent: str, query: str
    ) -> Dict[str, Any]:
        """
        POST /v1beta/interactions → interaction_id 획득.

        Returns:
          {"interaction_id": str | None, "error": str | None}
        """
        payload = {
            "input": query,
            "agent": agent,
            "background": True,
        }

        try:
            resp = httpx.post(
                _INTERACTIONS_URL,
                headers={
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30.0,
            )
        except httpx.TimeoutException as e:
            return {"interaction_id": None, "error": f"submit timeout: {e}"}
        except httpx.HTTPError as e:
            return {"interaction_id": None, "error": f"submit error: {e}"}

        if resp.status_code >= 400:
            return {
                "interaction_id": None,
                "error": f"submit HTTP {resp.status_code}: {resp.text[:200]}",
            }

        body = resp.json()
        interaction_id = str(body.get("id") or "").strip()
        if not interaction_id:
            return {"interaction_id": None, "error": "submit response missing 'id'"}

        return {"interaction_id": interaction_id, "error": None}

    # ---------------------------------------------------------------------
    # Deep Research: 폴링
    # ---------------------------------------------------------------------

    def _poll_until_complete(
        self, api_key: str, interaction_id: str, timeout: float
    ) -> Dict[str, Any] | None:
        """
        GET /v1beta/interactions/{id} 를 poll_interval 간격으로 반복.

        Returns:
          최종 body (completed/failed/cancelled) 또는 None (타임아웃).
        """
        max_wait = min(timeout, self.max_wait)
        elapsed = 0.0
        poll_url = f"{_INTERACTIONS_URL}/{interaction_id}"
        headers = {"x-goog-api-key": api_key}

        while elapsed < max_wait:
            time.sleep(self.poll_interval)
            elapsed += self.poll_interval

            try:
                resp = httpx.get(poll_url, headers=headers, timeout=30.0)
            except httpx.HTTPError:
                continue  # 일시적 오류 → 다음 폴링

            if resp.status_code >= 400:
                continue  # 일시적 4xx/5xx → 다음 폴링

            try:
                body = resp.json()
            except Exception:
                continue

            status = body.get("status", "")
            if status in _DR_TERMINAL_STATUSES:
                return body
            # in_progress → 계속

        return None  # 타임아웃

    # ---------------------------------------------------------------------
    # Interactions 응답 파싱 (deep_research 전용)
    # ---------------------------------------------------------------------

    def _parse_interaction_result(
        self, body: Dict[str, Any], agent: str, interaction_id: str
    ) -> ResearchResult:
        """Interactions API 완료된 응답 → ResearchResult."""
        outputs = body.get("outputs")
        if not isinstance(outputs, list) or not outputs:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=agent,
                error="no outputs in interaction result",
                raw_meta={"interaction_id": interaction_id},
            )

        # 마지막 output이 최종 보고서 (Gemini 공식 예시 기준)
        report = _extract_interaction_text(outputs)
        if not report:
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=agent,
                error="empty report in interaction outputs",
                raw_meta={"interaction_id": interaction_id},
            )

        # Interactions API에서 citations는 outputs[last].citations 또는 sources에 있을 수 있음
        citations = _extract_interaction_citations(outputs)

        # usage 정보 (있을 수도 있고 없을 수도 있음)
        usage = body.get("usage") or body.get("usageMetadata") or {}
        cost = _calculate_cost(usage, self._config)

        return ResearchResult(
            adapter_name=self.name,
            status=STATUS_SUCCESS,
            report=report,
            citations=citations,
            model=agent,
            cost_usd=cost,
            raw_meta={
                "usage": usage,
                "interaction_id": interaction_id,
                "mode": self.mode,
            },
        )

    # ---------------------------------------------------------------------
    # generateContent 응답 파싱 (web_search 전용 — 기존)
    # ---------------------------------------------------------------------

    def _parse_generate_content(
        self, body: Dict[str, Any], model: str
    ) -> ResearchResult:
        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates:
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

        report = _extract_text_from_parts(candidate.get("content"))
        if not report:
            finish = candidate.get("finishReason", "")
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                model=model,
                error=f"empty report (finishReason={finish})" if finish else "empty report",
                raw_meta={"finish_reason": finish},
            )

        citations = _extract_grounding_citations(candidate.get("grounding_metadata"))

        usage = body.get("usageMetadata") or {}
        cost = _calculate_cost(usage, self._config)

        return ResearchResult(
            adapter_name=self.name,
            status=STATUS_SUCCESS,
            report=report,
            citations=citations,
            model=model,
            cost_usd=cost,
            raw_meta={"usage": usage, "mode": self.mode},
        )


# ---------------------------------------------------------------------------
# 헬퍼 — API 키 / 모델 해석
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """GEMINI_API_KEY 우선, 없으면 GOOGLE_API_KEY."""
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        key = os.environ.get(var, "").strip()
        if key:
            return key
    return ""


def _resolve_model(config: Dict[str, Any]) -> str:
    env_var = config["env_var"]
    default = config["default_model"]
    return (os.environ.get(env_var, "").strip() or default)


# ---------------------------------------------------------------------------
# 헬퍼 — generateContent 파싱 (기존)
# ---------------------------------------------------------------------------

def _extract_text_from_parts(content: Any) -> str:
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


# ---------------------------------------------------------------------------
# 헬퍼 — Interactions API 파싱 (신규)
# ---------------------------------------------------------------------------

def _extract_interaction_text(outputs: Any) -> str:
    """
    Interactions outputs 배열에서 텍스트 추출.

    공식 예시: outputs[-1].text 가 최종 보고서.
    여러 텍스트 output이 있을 경우 마지막 것을 우선, 없으면 전체 이어붙임.
    """
    if not isinstance(outputs, list):
        return ""

    # 마지막부터 역탐색 — 첫 번째 유효 text 반환
    for output in reversed(outputs):
        if not isinstance(output, dict):
            continue
        text = output.get("text")
        if isinstance(text, str) and text.strip():
            return text

    return ""


def _extract_interaction_citations(outputs: Any) -> List[ResearchCitation]:
    """
    Interactions outputs 에서 citations 추출.
    
    Gemini Interactions API는 outputs[last].citations 또는 outputs[last].sources
    형태로 인용을 제공 (API가 preview라 구조 변동 가능).
    """
    if not isinstance(outputs, list):
        return []

    seen_urls = set()
    result: List[ResearchCitation] = []

    # outputs 전체 순회 — citations 또는 sources 필드 탐색
    for output in outputs:
        if not isinstance(output, dict):
            continue

        # citations 필드
        cits = output.get("citations")
        if isinstance(cits, list):
            for cit in cits:
                if not isinstance(cit, dict):
                    continue
                url = str(cit.get("uri") or cit.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                result.append(ResearchCitation(
                    url=url,
                    title=str(cit.get("title", "")),
                    snippet=str(cit.get("snippet", "")),
                ))

        # sources 필드 (대안)
        sources = output.get("sources")
        if isinstance(sources, list):
            for src in sources:
                if not isinstance(src, dict):
                    continue
                url = str(src.get("uri") or src.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                result.append(ResearchCitation(
                    url=url,
                    title=str(src.get("title", "")),
                    snippet=str(src.get("snippet", "")),
                ))

    return result


def _extract_error_message(body: Dict[str, Any]) -> str:
    """실패한 interaction에서 에러 메시지 추출."""
    err = body.get("error")
    if isinstance(err, dict):
        msg = err.get("message")
        if msg:
            return str(msg)
    elif isinstance(err, str) and err:
        return err
    return ""


# ---------------------------------------------------------------------------
# 헬퍼 — 비용 계산
# ---------------------------------------------------------------------------

def _calculate_cost(usage: Dict[str, Any], config: Dict[str, Any]) -> float:
    """
    Gemini usage 기반 비용 계산.

    필드:
      - generateContent: promptTokenCount / candidatesTokenCount
      - Interactions API: input_tokens / output_tokens (혹은 generateContent 스타일)
    """
    if not isinstance(usage, dict):
        return 0.0

    def _safe_int(val) -> int:
        try:
            return max(0, int(val or 0))
        except (TypeError, ValueError):
            return 0

    # 두 필드명 포맷 모두 시도
    input_tokens = _safe_int(usage.get("promptTokenCount") or usage.get("input_tokens"))
    output_tokens = _safe_int(usage.get("candidatesTokenCount") or usage.get("output_tokens"))

    cost = (
        (input_tokens * config["input_rate_per_m"]) / 1_000_000.0
        + (output_tokens * config["output_rate_per_m"]) / 1_000_000.0
    )
    return round(cost, 6)
