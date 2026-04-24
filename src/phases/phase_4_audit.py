"""
Phase 4 · AI 교차 감사 (Day 120~)

역할: Phase 3의 target_doc을 3인 감사관이 병렬 검증한 뒤,
      통합 LLM이 피드백을 합쳐 고도화 문서 생성.

3감사관 (scope.md v4 §Phase 4):
  - 구조 감사관 (Claude Opus 4.7)     : 논리 일관성, 누락, 중복, 구조
  - 균형 감사관 (GPT-5.4)             : 편향, 과장, 반대 관점 누락
  - 사실 감사관 (Gemini 3.1 Pro)     : 사실 오류, 출처 빈약

통합 LLM (Claude Sonnet 4.6 — Step 14-2 전환):
  - 3감사관과 독립적 시선 (동류 편향 방지)
  - 반복 실행 시 Anthropic 캐싱 90% 할인 활용
  - base_info_doc을 참조해 기반 사실 유지

실행 구조:
  target_doc + base_info_doc(참조)
    ↓
    [구조 감사] ─┐
    [균형 감사] ─┼──(병렬)──→ audits dict
    [사실 감사] ─┘
    ↓
    [통합 LLM] ── (순차, 1회)
    ↓
  synthesized_doc

정책:
  - 기본 ON (PHASE_4_ENABLED=true), 끄면 skipped 상태로 target_doc 그대로 반환
  - partial 허용: 1개 이상 감사관 성공하면 통합 진행
  - 모든 감사관 실패 → status=failed, 원본 문서 유지
  - 통합 LLM 실패 → 감사 결과는 보존, synthesized_doc만 None
  - 1 라운드 (N 라운드는 v4.1로 이연)

환경변수:
  PHASE_4_ENABLED=true
  OPENROUTER_API_KEY
  AUDITOR_STRUCTURE_MODEL=anthropic/claude-opus-4.7
  AUDITOR_BALANCE_MODEL=openai/gpt-5.4
  AUDITOR_FACT_MODEL=google/gemini-3.1-pro-preview
  AUDITOR_SYNTHESIZER_MODEL=anthropic/claude-sonnet-4-6
  AUDITOR_TIMEOUT=90.0
  AUDITOR_MAX_WORKERS=3
"""
from __future__ import annotations

from src.utils.llm_utils import call_llm

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.store.artifact_store import utc_now_iso


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

AUDITOR_STRUCTURE = "structure"
AUDITOR_BALANCE = "balance"
AUDITOR_FACT = "fact"

_ALL_AUDITORS = [AUDITOR_STRUCTURE, AUDITOR_BALANCE, AUDITOR_FACT]

_DEFAULT_MODELS = {
    AUDITOR_STRUCTURE: "anthropic/claude-opus-4.7",
    AUDITOR_BALANCE:   "openai/gpt-5.4",
    AUDITOR_FACT:      "google/gemini-3.1-pro-preview",
}

_SYNTHESIZER_DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

@dataclass
class CrossAuditResult:
    """Phase 4 전체 결과."""
    enabled: bool = True
    round: int = 1

    # 3감사관별 결과
    # {auditor_name: {"status": ..., "feedback": str, "error": str|None, "model": str}}
    audits: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # 통합 결과
    synthesized_doc: Optional[Dict[str, Any]] = None   # {"document": str, "created_at": str}

    # 원본 (비교용)
    original_doc: Optional[Dict[str, Any]] = None

    status: str = STATUS_SKIPPED
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "round": self.round,
            "audits": self.audits,
            "synthesized_doc": self.synthesized_doc,
            "original_doc": self.original_doc,
            "status": self.status,
            "error": self.error,
        }

    @property
    def successful_auditors(self) -> int:
        return sum(
            1 for a in self.audits.values()
            if a.get("status") == STATUS_SUCCESS
        )

    @property
    def is_success(self) -> bool:
        """감사 1개 이상 성공 + 통합 문서 생성됨."""
        return (
            self.status == STATUS_SUCCESS
            and self.synthesized_doc is not None
        )


# ---------------------------------------------------------------------------
# LLM 프롬프트 — 3감사관
# ---------------------------------------------------------------------------

_PROMPT_STRUCTURE_AUDITOR = """\
당신은 **구조 감사관**입니다. 정체성:
"차갑게 구조를 부수고 다시 세우는 감사관"

## 감사 원칙
- 논리 흐름의 일관성을 엄격히 평가합니다.
- 섹션 간 중복, 누락, 불균형을 찾습니다.
- 결론이 서론과 본문을 제대로 뒷받침하는지 점검합니다.
- 독자가 문서를 따라가기 쉬운 순서인지 판정합니다.
- **감정이 아니라 골격**을 봅니다.

## 원본 사용자 요청
{raw_input}

## 감사 대상 문서
{target_document}

## 참고 자료 (기반정보 — 있다면)
{base_info_section}

## 출력 형식
마크다운으로 구조적 문제만 지적하세요. 해결책 제시는 간결하게.
장점 언급은 최소화. 문제 중심.
"""

_PROMPT_BALANCE_AUDITOR = """\
당신은 **균형 감사관**입니다. 정체성:
"한쪽으로 기운 문서를 중립으로 되돌리는 감사관"

## 감사 원칙
- 편향된 주장, 과장된 표현, 일방적 전제를 찾습니다.
- 누락된 반대 관점, 리스크, 대안을 지적합니다.
- 감정적 수사, 확정형 단언("반드시", "절대")의 남용을 찾습니다.
- 중립적이고 다면적인 관점으로 재작성될 수 있는 부분을 지적합니다.
- **칭찬이 아니라 균형**을 점검합니다.

## 원본 사용자 요청
{raw_input}

## 감사 대상 문서
{target_document}

## 참고 자료 (기반정보 — 있다면)
{base_info_section}

## 출력 형식
마크다운으로 편향·과장·누락된 반대 관점을 지적하세요.
각 지적에 구체적 근거를 붙이세요.
"""

_PROMPT_FACT_AUDITOR = """\
당신은 **사실 감사관**입니다. 정체성:
"현실과 최신 정보를 기준으로 사실을 검수하는 감사관"

## 감사 원칙
- 수치, 연도, 이름, 통계의 사실 여부를 점검합니다.
- 근거 없이 주장된 내용을 찾습니다.
- 출처가 불명확한 인용을 지적합니다.
- 기반정보 문서와 모순되는 서술을 찾습니다.
- 시대적 맥락(현재 연도·최신 트렌드)을 기준으로 검증합니다.
- **수사가 아니라 사실**을 점검합니다.

## 원본 사용자 요청
{raw_input}

## 감사 대상 문서
{target_document}

## 참고 자료 (기반정보 — 이것이 기준)
{base_info_section}

## 출력 형식
마크다운으로 사실 오류, 근거 빈약, 출처 불명 항목을 지적하세요.
각 지적에 "어떤 근거로 의심되는지" 명시하세요.
"""

_AUDITOR_PROMPTS = {
    AUDITOR_STRUCTURE: _PROMPT_STRUCTURE_AUDITOR,
    AUDITOR_BALANCE:   _PROMPT_BALANCE_AUDITOR,
    AUDITOR_FACT:      _PROMPT_FACT_AUDITOR,
}


# ---------------------------------------------------------------------------
# LLM 프롬프트 — 통합
# ---------------------------------------------------------------------------

_PROMPT_SYNTHESIZER = """\
당신은 **편집자**입니다. 3명의 감사관이 남긴 피드백을 검토하고,
원본 문서를 개선한 고도화 문서를 작성합니다.

## 원칙
1. **감사관 의견을 취사선택**: 모순되는 지적은 근거가 강한 쪽을 따릅니다.
2. **원본 강점 보존**: 피드백에 언급되지 않은 부분은 유지합니다.
3. **사실 감사가 최우선**: 사실 오류는 반드시 수정합니다.
4. **균형**: 편향 지적을 받은 부분은 반대 관점을 더합니다.
5. **구조**: 논리 흐름 지적을 반영해 섹션을 조정합니다.
6. **기반정보와 일관성 유지**: 기반정보 문서가 있다면 그 사실과 어긋나지 않게.
7. **전체 문서 반환**: 변경 부분만이 아닌 완성본.
8. **한국어**.

## 원본 사용자 요청
{raw_input}

## 원본 문서 (개선 대상)
{original_document}

## 기반정보 문서 (사실 기준)
{base_info_section}

## 감사관 피드백

### 구조 감사관 (Claude)
{structure_feedback}

### 균형 감사관 (GPT)
{balance_feedback}

### 사실 감사관 (Gemini)
{fact_feedback}

## 출력 형식
마크다운 전체 문서만 출력. 설명이나 코드 블록 감싸기 없이.
"""


# ---------------------------------------------------------------------------
# 공통 LLM 호출
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 섹션 빌더
# ---------------------------------------------------------------------------

def _build_base_info_section(base_info_doc: Optional[Dict[str, Any]]) -> str:
    """base_info_doc을 프롬프트 섹션으로 변환. None이면 placeholder."""
    if not base_info_doc or not isinstance(base_info_doc, dict):
        return "(기반정보 문서 없음)"
    doc = base_info_doc.get("document", "")
    if not isinstance(doc, str) or not doc.strip():
        return "(기반정보 문서 없음)"
    return doc.strip()


# ---------------------------------------------------------------------------
# 단일 감사관 실행
# ---------------------------------------------------------------------------

def _run_single_auditor(
    auditor_name: str,
    target_doc_text: str,
    raw_input: str,
    base_info_section: str,
    model: str,
    timeout: float,
) -> Dict[str, Any]:
    """
    단일 감사관 LLM 호출.
    반환: {"status": ..., "feedback": str, "error": str|None, "model": str}
    """
    prompt_template = _AUDITOR_PROMPTS.get(auditor_name)
    if not prompt_template:
        return {
            "status": STATUS_FAILED,
            "feedback": "",
            "error": f"알 수 없는 감사관: {auditor_name}",
            "model": model,
        }

    prompt = prompt_template.format(
        raw_input=raw_input.strip() if raw_input else "(원본 요청 없음)",
        target_document=target_doc_text,
        base_info_section=base_info_section,
    )

    feedback = call_llm(prompt, model, timeout)

    if feedback is None:
        return {
            "status": STATUS_FAILED,
            "feedback": "",
            "error": "LLM 호출 실패 또는 API 키 없음",
            "model": model,
        }

    if not feedback.strip():
        return {
            "status": STATUS_FAILED,
            "feedback": "",
            "error": "LLM 응답이 비어있음",
            "model": model,
        }

    return {
        "status": STATUS_SUCCESS,
        "feedback": feedback.strip(),
        "error": None,
        "model": model,
    }


# ---------------------------------------------------------------------------
# 통합 LLM 실행
# ---------------------------------------------------------------------------

def _run_synthesizer(
    original_doc_text: str,
    raw_input: str,
    base_info_section: str,
    audits: Dict[str, Dict[str, Any]],
    model: str,
    timeout: float,
) -> Optional[Dict[str, Any]]:
    """
    통합 LLM 호출. 실패 시 None.

    성공한 감사만 프롬프트에 포함. 실패한 감사는 "(감사 실패)"로 표시.
    """
    def _feedback_of(auditor: str) -> str:
        a = audits.get(auditor, {})
        if a.get("status") == STATUS_SUCCESS:
            return a.get("feedback", "")
        err = a.get("error", "알 수 없는 이유")
        return f"(감사 실패: {err})"

    prompt = _PROMPT_SYNTHESIZER.format(
        raw_input=raw_input.strip() if raw_input else "(원본 요청 없음)",
        original_document=original_doc_text,
        base_info_section=base_info_section,
        structure_feedback=_feedback_of(AUDITOR_STRUCTURE),
        balance_feedback=_feedback_of(AUDITOR_BALANCE),
        fact_feedback=_feedback_of(AUDITOR_FACT),
    )

    text = call_llm(prompt, model, timeout)
    if text is None or not text.strip():
        return None

    return {
        "document": text,
        "created_at": utc_now_iso(),
    }


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def run_cross_audit(
    target_doc: Dict[str, Any],
    raw_input: str = "",
    base_info_doc: Optional[Dict[str, Any]] = None,
) -> CrossAuditResult:
    """
    Phase 4 · 3감사관 + 통합 LLM 실행 (공개 API).

    Args:
      target_doc: 감사 대상 (Phase 3b 결과 또는 Phase 5 최신 버전)
                  {"document": str, "created_at": str}
      raw_input: 원본 사용자 요청
      base_info_doc: Phase 3a 기반정보 문서 (선택, 사실 감사관의 기준)

    Returns:
      CrossAuditResult (예외 전파 없음)

    실패 정책:
      - PHASE_4_ENABLED=false → status=skipped, target_doc 그대로
      - target_doc 유효성 실패 → status=failed
      - 모든 감사관 실패 → status=failed, synthesized_doc=None
      - 1개 이상 감사 성공 + 통합 성공 → status=success
      - 감사 성공하나 통합 실패 → status=failed, audits는 보존
    """
    # 1. ON/OFF 체크
    enabled = os.environ.get("PHASE_4_ENABLED", "true").strip().lower() != "false"
    if not enabled:
        return CrossAuditResult(
            enabled=False,
            original_doc=target_doc,
            status=STATUS_SKIPPED,
            error=None,
        )

    # 2. 입력 검증
    if not isinstance(target_doc, dict):
        return CrossAuditResult(
            enabled=True,
            status=STATUS_FAILED,
            error="target_doc이 dict가 아님",
        )

    target_text = target_doc.get("document", "")
    if not isinstance(target_text, str) or not target_text.strip():
        return CrossAuditResult(
            enabled=True,
            original_doc=target_doc,
            status=STATUS_FAILED,
            error="target_doc.document가 비어있음",
        )

    # 3. 설정 로드
    timeout = float(os.environ.get("AUDITOR_TIMEOUT", "90.0"))
    max_workers = int(os.environ.get("AUDITOR_MAX_WORKERS", "3"))
    max_workers = max(1, min(max_workers, 5))

    models = {
        AUDITOR_STRUCTURE: os.environ.get(
            "AUDITOR_STRUCTURE_MODEL", _DEFAULT_MODELS[AUDITOR_STRUCTURE]),
        AUDITOR_BALANCE: os.environ.get(
            "AUDITOR_BALANCE_MODEL", _DEFAULT_MODELS[AUDITOR_BALANCE]),
        AUDITOR_FACT: os.environ.get(
            "AUDITOR_FACT_MODEL", _DEFAULT_MODELS[AUDITOR_FACT]),
    }
    synthesizer_model = os.environ.get(
        "AUDITOR_SYNTHESIZER_MODEL", _SYNTHESIZER_DEFAULT_MODEL)

    base_info_section = _build_base_info_section(base_info_doc)

    # 4. 3감사관 병렬 실행
    audits: Dict[str, Dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_name = {
            executor.submit(
                _run_single_auditor,
                auditor_name,
                target_text.strip(),
                raw_input,
                base_info_section,
                models[auditor_name],
                timeout,
            ): auditor_name
            for auditor_name in _ALL_AUDITORS
        }

        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                audits[name] = future.result()
            except Exception as exc:
                audits[name] = {
                    "status": STATUS_FAILED,
                    "feedback": "",
                    "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                    "model": models.get(name, "unknown"),
                }

    # 5. 감사 성공 수 확인
    successful_count = sum(
        1 for a in audits.values()
        if a.get("status") == STATUS_SUCCESS
    )

    if successful_count == 0:
        return CrossAuditResult(
            enabled=True,
            round=1,
            audits=audits,
            original_doc=target_doc,
            status=STATUS_FAILED,
            error="모든 감사관이 실패했습니다",
        )

    # 6. 통합 LLM 실행
    synthesized = _run_synthesizer(
        original_doc_text=target_text.strip(),
        raw_input=raw_input,
        base_info_section=base_info_section,
        audits=audits,
        model=synthesizer_model,
        timeout=timeout,
    )

    if synthesized is None:
        return CrossAuditResult(
            enabled=True,
            round=1,
            audits=audits,
            original_doc=target_doc,
            status=STATUS_FAILED,
            error="통합 LLM 호출 실패 — 감사 결과는 보존됨",
        )

    # 7. 성공 반환
    return CrossAuditResult(
        enabled=True,
        round=1,
        audits=audits,
        synthesized_doc=synthesized,
        original_doc=target_doc,
        status=STATUS_SUCCESS,
        error=None,
    )
