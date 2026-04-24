"""
Phase 1 · 서브주제 분해 (Day 115~, Step 14-2 전환)

역할: 사용자 요청을 리서치 가능한 탐색 단위(서브주제)로 분해.

입력:
  raw_input: 사용자 원본 요청 (Phase 0.5에서 possible로 판정된 것)
  feasibility: Phase 0.5 FeasibilityResult (참고용, 선택)

출력:
  DecomposeResult:
    subtopics: list[str]        — 5~8개 권장, 최대 10개
    decided_by: "llm" | "fallback"
    error: Optional[str]         — 실패 시 이유

Step 14-2 변경:
  - 로컬 call_llm 함수 삭제 (src.utils.llm_utils.call_llm과 이름 충돌 해소)
  - httpx 직접 호출 → call_llm_json 사용 (캐싱 + 재시도)
  - 기본 모델 Haiku 4.5로 다운그레이드
  - _parse_response 함수 삭제 (call_llm_json이 파싱 + 재시도 모두 처리)

환경변수:
  OPENROUTER_API_KEY
  DECOMPOSE_MODEL            — 기본: anthropic/claude-haiku-4-5
  DECOMPOSE_TIMEOUT          — 기본: 60.0 초
  DECOMPOSE_MIN_SUBTOPICS    — 기본: 3
  DECOMPOSE_MAX_SUBTOPICS    — 기본: 10
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from src.utils.llm_utils import call_llm_json


# ---------------------------------------------------------------------------
# 모델 / 타임아웃 설정
# ---------------------------------------------------------------------------

DECOMPOSE_MODEL = os.environ.get("DECOMPOSE_MODEL", "anthropic/claude-haiku-4-5")

try:
    DECOMPOSE_TIMEOUT = float(os.environ.get("DECOMPOSE_TIMEOUT", "60.0"))
except (ValueError, TypeError):
    DECOMPOSE_TIMEOUT = 60.0


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

@dataclass
class DecomposeResult:
    """Phase 1 서브주제 분해 결과."""
    subtopics: list[str]
    decided_by: str = "llm"
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "subtopics": self.subtopics,
            "decided_by": self.decided_by,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# 설정 (환경변수 동적 로드)
# ---------------------------------------------------------------------------

_DEFAULT_MIN = 3
_DEFAULT_MAX = 10
_RECOMMENDED_RANGE = "5~8"
_SUBTOPIC_MAX_LEN = 100


def _get_min_max() -> tuple[int, int]:
    """환경변수에서 min/max 로드. 잘못된 값이면 기본값."""
    try:
        min_n = int(os.environ.get("DECOMPOSE_MIN_SUBTOPICS", _DEFAULT_MIN))
    except ValueError:
        min_n = _DEFAULT_MIN
    try:
        max_n = int(os.environ.get("DECOMPOSE_MAX_SUBTOPICS", _DEFAULT_MAX))
    except ValueError:
        max_n = _DEFAULT_MAX
    min_n = max(1, min_n)
    max_n = max(min_n, min(max_n, 20))
    return min_n, max_n


# ---------------------------------------------------------------------------
# LLM 프롬프트
# ---------------------------------------------------------------------------

_LLM_PROMPT = """\
당신은 사용자 요청을 리서치 가능한 서브주제로 분해하는 분해기입니다.

## 사용자 요청
{raw_input}

## 분해 원칙
1. **독립 조사 가능**: 각 서브주제는 서로 참조 없이 단독으로 리서치 가능해야 함
2. **합치면 전체 커버**: 모든 서브주제를 합치면 사용자 요청을 충분히 다룰 수 있어야 함
3. **중복 없음**: 서브주제끼리 내용이 겹치면 안 됨
4. **{range}개 권장**: 너무 적으면 얕고, 너무 많으면 분산됨
5. **한국어**: 서브주제는 한국어로 작성

## 좋은 예시

요청: "앱 사업계획서 써줘"
→ ["사업계획서 표준 구성과 작성 방법론",
   "타깃 시장 규모와 성장 추세",
   "경쟁사 분석 프레임워크와 벤치마킹 기법",
   "차별화 전략과 포지셔닝 방법",
   "수익 모델 유형과 선정 기준",
   "재무 계획 수립 템플릿과 핵심 지표"]

요청: "로그인 버그 수정해줘"
→ ["주요 웹 프레임워크의 인증 처리 흐름",
   "세션/토큰 기반 인증의 일반적 버그 유형",
   "로그인 실패 디버깅 체크리스트와 로그 분석법",
   "안전한 비밀번호 검증 및 해싱 베스트프랙티스",
   "실제 오픈소스 프로젝트의 로그인 버그 수정 사례"]

## 응답 형식
반드시 아래 JSON만 출력하세요. 설명이나 마크다운 없이 JSON만.

{{
  "subtopics": ["서브주제 1", "서브주제 2", "..."]
}}
"""


# ---------------------------------------------------------------------------
# 내부 헬퍼 — LLM 호출 (call_llm_json 사용)
# ---------------------------------------------------------------------------

def _fetch_subtopics(raw_input: str) -> Optional[list[str]]:
    """
    LLM 호출해서 서브주제 리스트 반환.
    실패 시 None (파싱 실패, 네트워크 실패, API 키 없음 모두 None).

    주의: 함수명이 call_llm이 아닌 이유는 src.utils.llm_utils.call_llm과 충돌 방지.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None

    prompt = _LLM_PROMPT.format(
        raw_input=raw_input,
        range=_RECOMMENDED_RANGE,
    )

    data = call_llm_json(
        prompt=prompt,
        model=DECOMPOSE_MODEL,
        timeout=DECOMPOSE_TIMEOUT,
    )

    if data is None or not isinstance(data, dict):
        return None

    subtopics = data.get("subtopics")
    if not isinstance(subtopics, list):
        return None

    # 문자열만 필터링 (None, int 등 제거)
    return [str(s) for s in subtopics if s]


# ---------------------------------------------------------------------------
# 후처리 — 중복/빈/초과 정리
# ---------------------------------------------------------------------------

def _sanitize(subtopics: list[str], max_n: int) -> list[str]:
    """
    후처리:
      - 공백 제거
      - 빈 문자열 제거
      - 중복 제거 (순서 유지, 대소문자 무시)
      - 너무 긴 항목 자르기
      - max_n개로 잘라내기
    """
    cleaned = []
    seen = set()
    for s in subtopics:
        if not isinstance(s, str):
            continue
        t = s.strip()
        if not t:
            continue
        if len(t) > _SUBTOPIC_MAX_LEN:
            t = t[:_SUBTOPIC_MAX_LEN].rstrip() + "…"
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(t)
        if len(cleaned) >= max_n:
            break
    return cleaned


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def decompose_request(
    raw_input: str,
    feasibility: Optional[dict] = None,
) -> DecomposeResult:
    """
    Phase 1 · 서브주제 분해 (공개 API).

    호출 예:
        result = decompose_request("사업계획서 써줘")
        if len(result.subtopics) >= 3:
            # Phase 2로 진행

    입력이 비어있거나 매우 짧으면 fallback.
    LLM 호출 실패 시에도 fallback (예외 전파 없음).
    """
    min_n, max_n = _get_min_max()

    # 1. 입력 검증
    text = (raw_input or "").strip()
    if not text:
        return DecomposeResult(
            subtopics=[],
            decided_by="fallback",
            error="입력이 비어있음",
        )

    # 2. LLM 호출
    raw_subtopics = _fetch_subtopics(text)

    if raw_subtopics is None:
        return DecomposeResult(
            subtopics=[text[:_SUBTOPIC_MAX_LEN]],
            decided_by="fallback",
            error="LLM 호출 실패 또는 API 키 없음",
        )

    # 3. 후처리
    cleaned = _sanitize(raw_subtopics, max_n)

    if not cleaned:
        return DecomposeResult(
            subtopics=[text[:_SUBTOPIC_MAX_LEN]],
            decided_by="fallback",
            error="LLM 응답에서 유효한 서브주제 없음",
        )

    # 4. 최소 개수 체크 — 부족해도 있는 만큼 반환
    return DecomposeResult(
        subtopics=cleaned,
        decided_by="llm",
        error=None if len(cleaned) >= min_n else f"서브주제가 권장치({min_n}개)보다 적음",
    )
