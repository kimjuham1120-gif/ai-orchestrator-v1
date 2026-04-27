"""
Phase 3 · 2문서 합성 (Day 117~, Step 14-2 모델 전환)

역할: Phase 2 리서치 결과를 받아 2개 문서를 독립 생성.
  - Phase 3a: 기반정보 문서 (base_info_doc) — 리서치 정리, 범용 참조
  - Phase 3b: 목표 산출물 초안 (target_doc) — 사용자 요청 맞춤

입력:
  raw_input: str                    사용자 원본 요청
  parallel_research: dict           Phase 2 결과 (ParallelResearchResult.data)
  feasibility: Optional[dict]       Phase 0.5 결과 (참고용)

출력:
  SynthesizeResult:
    base_info_doc: Optional[dict]   {"document": str, "created_at": str}
    target_doc: Optional[dict]      {"document": str, "created_at": str}
    base_info_status: "success" | "failed" | "skipped"
    target_doc_status: "success" | "failed" | "skipped"
    error: Optional[str]

실패 정책:
  - 3a, 3b는 독립 실행 — 하나 실패해도 다른 건 시도
  - 둘 다 실패 → error 기록 (예외 전파 X, 호출자가 판단)
  - 리서치 결과 없음 → 둘 다 skipped

Step 14-2 변경:
  - 기본 모델 openai/gpt-5.4 → anthropic/claude-sonnet-4-6
    (Anthropic 캐싱 90% 할인 활용, GPT-5.4 대비 유사 품질·동등 비용)

환경변수:
  OPENROUTER_API_KEY
  SYNTHESIS_MODEL        — 기본: anthropic/claude-sonnet-4-6
  SYNTHESIS_TIMEOUT      — 기본: 90.0 초
"""
from __future__ import annotations

from src.utils.llm_utils import call_llm

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.store.artifact_store import utc_now_iso


# ---------------------------------------------------------------------------
# 모델 / 타임아웃 설정
# ---------------------------------------------------------------------------

SYNTHESIS_MODEL = os.environ.get("SYNTHESIS_MODEL", "anthropic/claude-sonnet-4-6")

try:
    SYNTHESIS_TIMEOUT = float(os.environ.get("SYNTHESIS_TIMEOUT", "90.0"))
except (ValueError, TypeError):
    SYNTHESIS_TIMEOUT = 90.0


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class SynthesizeResult:
    """Phase 3 합성 결과."""
    base_info_doc: Optional[dict] = None       # {"document": str, "created_at": str}
    target_doc: Optional[dict] = None

    base_info_status: str = STATUS_SKIPPED
    target_doc_status: str = STATUS_SKIPPED

    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "base_info_doc": self.base_info_doc,
            "target_doc": self.target_doc,
            "base_info_status": self.base_info_status,
            "target_doc_status": self.target_doc_status,
            "error": self.error,
        }

    @property
    def any_success(self) -> bool:
        """3a 또는 3b 중 하나라도 성공했는가."""
        return (
            self.base_info_status == STATUS_SUCCESS
            or self.target_doc_status == STATUS_SUCCESS
        )


# ---------------------------------------------------------------------------
# 리서치 결과 요약 (프롬프트 주입용)
# ---------------------------------------------------------------------------

def _format_research_for_prompt(parallel_research: Dict[str, Dict[str, Any]]) -> str:
    """
    Phase 2 결과를 LLM 프롬프트에 주입 가능한 텍스트로 포맷.

    입력 구조:
      {subtopic: {adapter: {"status": ..., "claims": [...], "error": ...}}}

    출력: 사람이 읽을 수 있는 마크다운 형식
    """
    if not parallel_research:
        return "(리서치 결과 없음)"

    lines = []
    for subtopic, adapters in parallel_research.items():
        lines.append(f"## 서브주제: {subtopic}")

        all_claims = []
        for adapter_name, adapter_result in adapters.items():
            if adapter_result.get("status") != "success":
                continue
            claims = adapter_result.get("claims") or []
            for c in claims:
                text = c.get("text", "") if isinstance(c, dict) else str(c)
                source = c.get("source", "") if isinstance(c, dict) else ""
                if text:
                    all_claims.append((adapter_name, text, source))

        if not all_claims:
            lines.append("  (유효한 리서치 결과 없음)")
        else:
            for adapter_name, text, source in all_claims:
                src_note = f" [{source}]" if source else ""
                lines.append(f"  - ({adapter_name}) {text}{src_note}")

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM 프롬프트 — Phase 3a · 기반정보 문서
# ---------------------------------------------------------------------------

_PROMPT_3A_BASE_INFO = """\
당신은 리서치 결과를 정리해 **범용 참조 문서**(기반정보 문서)를 작성하는 편집자입니다.

## 원칙
1. **리서치 결과만 사용**: 제공된 리서치 근거 밖의 내용을 지어내지 않습니다.
2. **사용자 맥락 무시**: 특정 프로젝트가 아닌 해당 주제 일반에 적용 가능한 형태로 작성합니다.
3. **구조화**: 소제목과 문단으로 명확히 구분합니다.
4. **출처 인용**: 중요한 주장에는 (출처: adapter_name) 표기를 유지합니다.
5. **한국어**: 문서 본문은 한국어로 작성합니다.

## 리서치 결과
{research_summary}

## 원본 요청 (맥락 참고용, 문서에 직접 쓰지 않음)
{raw_input}

## 출력 형식
마크다운 문서 본문만 출력하세요. 설명이나 코드 블록 감싸기 없이.
"""


# ---------------------------------------------------------------------------
# LLM 프롬프트 — Phase 3b · 목표 산출물 초안
# ---------------------------------------------------------------------------

_PROMPT_3B_TARGET = """\
당신은 사용자 요청에 **직접 답하는 산출물**(목표 산출물 초안)을 작성하는 전문 작가입니다.

## 원칙
1. **사용자 요청에 맞춤**: 원본 요청이 원하는 형식/톤/목적에 정확히 답합니다.
2. **리서치를 근거로**: 제공된 리서치 결과를 활용하되, 단순 나열이 아닌 재구성으로.
3. **실제 납품 가능한 품질**: 사용자가 그대로 활용할 수 있는 완성도.
4. **출처 인용은 선택**: 중요한 수치/인용에만 출처 표기, 일반 서술은 자연스럽게.
5. **한국어**: 한국어로 작성.
{template_instruction}
## 원본 요청
{raw_input}

## 리서치 결과 (근거 자료)
{research_summary}
{template_section}
## 출력 형식
마크다운 문서 본문만 출력하세요. 설명이나 코드 블록 감싸기 없이.
"""


# ---------------------------------------------------------------------------
# LLM 호출 (공통)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 단일 문서 생성 (3a 또는 3b)
# ---------------------------------------------------------------------------

def _synthesize_single(
    prompt_template: str,
    raw_input: str,
    research_summary: str,
    template_text: str = "",
) -> tuple[Optional[dict], str, Optional[str]]:
    """
    단일 문서 생성.
    반환: (document_dict_or_None, status, error_or_None)
    """
    # 양식 섹션 — 양식 텍스트 있을 때만 프롬프트에 추가
    if template_text and template_text.strip():
        template_instruction = (
            "\n6. **양식 준수**: 아래 [양식 파일] 섹션의 구조·항목·순서를 그대로 따라 작성합니다. "
            "사용자가 제공한 양식이므로 임의로 항목을 빼거나 추가하지 않습니다.\n"
        )
        template_section = (
            f"\n## 양식 파일 (사용자가 지정한 출력 구조)\n{template_text.strip()}\n"
        )
    else:
        template_instruction = ""
        template_section = ""

    # 프롬프트 템플릿이 양식 placeholder를 가지지 않을 수도 있음 (3a)
    # → 안전하게 대체
    try:
        prompt = prompt_template.format(
            raw_input=raw_input,
            research_summary=research_summary,
            template_instruction=template_instruction,
            template_section=template_section,
        )
    except KeyError:
        # 양식 placeholder 없는 옛 템플릿용 fallback
        prompt = prompt_template.format(
            raw_input=raw_input,
            research_summary=research_summary,
        )

    text = call_llm(prompt, SYNTHESIS_MODEL, SYNTHESIS_TIMEOUT)

    if text is None:
        return None, STATUS_FAILED, "LLM 호출 실패 또는 API 키 없음"

    if not text.strip():
        return None, STATUS_FAILED, "LLM 응답이 비어있음"

    doc = {
        "document": text,
        "created_at": utc_now_iso(),
    }
    return doc, STATUS_SUCCESS, None


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def synthesize_documents(
    raw_input: str,
    parallel_research: Dict[str, Dict[str, Any]],
    feasibility: Optional[dict] = None,
    template_text: str = "",
) -> SynthesizeResult:
    """
    Phase 3 · 2문서 합성 (공개 API).

    3a, 3b를 독립 실행. 한쪽 실패해도 다른 쪽은 시도.

    Args:
      raw_input: 사용자 원본 요청
      parallel_research: Phase 2 결과 (dict 형태)
      feasibility: Phase 0.5 결과 (현재 참고만)
      template_text: 양식 파일 텍스트 (선택, target_doc만 적용)

    Returns:
      SynthesizeResult (예외 전파 없음)
    """
    # 입력 검증
    text = (raw_input or "").strip()
    if not text:
        return SynthesizeResult(
            error="raw_input이 비어있음",
        )

    if not parallel_research:
        return SynthesizeResult(
            error="parallel_research가 비어있음",
        )

    # 성공한 리서치가 하나라도 있는지 확인
    has_any_success = False
    for subtopic_data in parallel_research.values():
        for adapter_result in subtopic_data.values():
            if adapter_result.get("status") == STATUS_SUCCESS:
                has_any_success = True
                break
        if has_any_success:
            break

    if not has_any_success:
        return SynthesizeResult(
            error="parallel_research에 성공한 리서치 결과가 없음",
        )

    # 리서치 요약 텍스트 준비
    research_summary = _format_research_for_prompt(parallel_research)

    # Phase 3a — 기반정보 문서 (양식 적용 안 함 — 일반 참조용)
    base_info_doc, base_status, base_error = _synthesize_single(
        _PROMPT_3A_BASE_INFO, text, research_summary
    )

    # Phase 3b — 목표 산출물 초안 (양식 적용)
    target_doc, target_status, target_error = _synthesize_single(
        _PROMPT_3B_TARGET, text, research_summary,
        template_text=template_text,
    )

    # 결과 조립
    result = SynthesizeResult(
        base_info_doc=base_info_doc,
        target_doc=target_doc,
        base_info_status=base_status,
        target_doc_status=target_status,
    )

    # 에러 메시지 병합
    errors = []
    if base_error:
        errors.append(f"3a: {base_error}")
    if target_error:
        errors.append(f"3b: {target_error}")
    if errors:
        result.error = " | ".join(errors)

    return result
