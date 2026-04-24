"""
Phase 0.5 · 처리 가능성 게이트 (Day 114~, Step 14-2 전환)

역할: 사용자 입력이 시스템 범위 안인지 판정.

판정 결과:
  possible       — 문서/앱 산출물로 풀 수 있음 → Phase 1로
  out_of_scope   — 시스템 범위 밖 → 정중 거절
  ambiguous      — 목표 불명확 → 사용자에게 되물음

2단계 판정 구조:
  1단계: 규칙 기반 (비용 0, 즉시)
  2단계: LLM 판정 (1단계 미결 시만)

Step 14-2 변경:
  - httpx 직접 호출 → call_llm_json 사용 (캐싱 + 재시도)
  - 기본 모델 Haiku 4.5로 다운그레이드
  - _parse_llm_response 삭제 (call_llm_json이 파싱 + 재시도 모두 처리)

환경변수:
  OPENROUTER_API_KEY         — LLM 판정용 (없으면 규칙 기반만)
  FEASIBILITY_MODEL          — 기본: anthropic/claude-haiku-4-5
  FEASIBILITY_TIMEOUT        — 기본: 30.0 초
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from src.utils.llm_utils import call_llm_json


# ---------------------------------------------------------------------------
# 모델 / 타임아웃 설정
# ---------------------------------------------------------------------------

FEASIBILITY_MODEL = os.environ.get("FEASIBILITY_MODEL", "anthropic/claude-haiku-4-5")

try:
    FEASIBILITY_TIMEOUT = float(os.environ.get("FEASIBILITY_TIMEOUT", "30.0"))
except (ValueError, TypeError):
    FEASIBILITY_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

VERDICT_POSSIBLE = "possible"
VERDICT_OUT_OF_SCOPE = "out_of_scope"
VERDICT_AMBIGUOUS = "ambiguous"

_ALL_VERDICTS = {VERDICT_POSSIBLE, VERDICT_OUT_OF_SCOPE, VERDICT_AMBIGUOUS}


@dataclass
class FeasibilityResult:
    """Phase 0.5 판정 결과."""
    verdict: str
    reason: str
    suggested_clarification: Optional[str] = None
    decided_by: str = "rule"

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "suggested_clarification": self.suggested_clarification,
            "decided_by": self.decided_by,
        }


# ---------------------------------------------------------------------------
# 1단계 — 규칙 기반 판정
# ---------------------------------------------------------------------------

_MIN_LENGTH = 5

_OUT_OF_SCOPE_PATTERNS = [
    # 실시간 정보
    (r"(오늘|지금|현재|실시간).*(날씨|기온|온도|비|눈|미세먼지)", "실시간 날씨 정보"),
    (r"(지금|현재|실시간).*(주가|환율|코인|비트코인)", "실시간 금융 시세"),
    (r"(지금|현재|오늘|실시간).*(뉴스|속보|이슈)", "실시간 뉴스"),
    (r"(현재|실시간).*시간", "실시간 시각"),

    # 물리 세계 조작
    (r"(택시|우버|배달).*(불러|호출|시켜)", "실시간 이동/배달 호출"),
    (r"(전화|통화).*(걸어|해줘)", "실시간 통신"),

    # 외부 계정 연동
    (r"(내|나의|제).*(이메일|메일|gmail).*(확인|읽|보여)", "개인 이메일 접근"),
    (r"(내|나의|제).*(캘린더|일정|스케줄).*(확인|보여)", "개인 캘린더 접근"),
    (r"(내|나의|제).*(sns|인스타|페북|트위터|카톡)", "SNS 계정 접근"),

    # 창작 예술
    (r"(그림|이미지|사진|일러스트).*(그려|만들어|생성)", "이미지 생성"),
    (r"(작곡|노래|음악).*(만들어|작곡|생성)", "음악 생성"),
    (r"(음성|목소리|tts).*(만들어|합성|생성)", "음성 합성"),
    (r"(영상|동영상|비디오).*(만들어|편집|생성)", "영상 생성"),

    # 책임 자문
    (r"(법적|법률)\s*(자문|상담|판단)", "법률 자문"),
    (r"(의료|의학)\s*(진단|자문|처방)", "의료 자문"),
    (r"(투자|매매|재테크)\s*(결정|판단|추천해줘)", "금융 투자 결정"),

    # 대화 상대
    (r"^(심심|외로워|같이\s*놀)", "실시간 대화 상대"),
    (r"(게임|롤|오버워치).*(같이|함께)\s*(하자|해)", "실시간 게임 상대"),
    (r"같이\s*(게임|롤|오버워치).*(하자|해)", "실시간 게임 상대"),
]

_PURE_ORDER_PATTERNS = [
    (r"(치킨|피자|커피|음식|식당).*(주문|시켜|배달).*(해줘|해주세요)", "실제 음식 주문"),
    (r"(택시|차).*(불러|예약).*(해줘|해주세요)", "교통 예약"),
]

_POSSIBLE_PATTERNS = [
    # 문서 산출물
    (r"(사업\s*계획서|기획서|제안서|보고서|레포트)", "문서 작성 요청"),
    (r"(분석|조사|리서치|정리|요약)\s*(해줘|부탁|원함)?", "정보 취득 요청"),
    (r"(전략|방안|계획)\s*(수립|제안|만들|써)", "전략 수립 요청"),
    (r"(매뉴얼|가이드|설명서|튜토리얼)\s*(만들|작성|써)", "가이드 작성 요청"),

    # 앱 개발
    (r"(기능|feature)\s*(추가|구현|개발|만들)", "기능 추가 요청"),
    (r"(버그|에러|오류)\s*(수정|고쳐|잡아|픽스)", "버그 수정 요청"),
    (r"(리팩터|리팩토링|refactor)", "리팩터링 요청"),
    (r"(코드\s*리뷰|code\s*review)", "코드 리뷰 요청"),
    (r"(앱|시스템|웹사이트|사이트|서비스|플랫폼)\s*(만들|개발|구축|제작)", "앱/시스템 구축 요청"),
    (r"(api|라이브러리|라우터|서버|데이터베이스|db|백엔드|프론트엔드)\s*(추가|구현|연동|개발|만들)", "기술 구현 요청"),
    (r"(연동|통합|integration)\s*(구현|해줘|개발)", "연동 구현 요청"),
]

_AMBIGUOUS_PATTERNS = [
    r"^(뭐|뭔가|아무거나|랜덤|뭐든)\s*(해|시켜|추천)",
    r"^(심심|재밌|즐거)",
    r"^(몰라|모르겠|정함)$",
]


def _rule_based_judge(raw_input: str) -> Optional[FeasibilityResult]:
    """1단계 규칙 기반 판정. 판정 가능하면 FeasibilityResult, 아니면 None."""
    text = raw_input.strip()

    # 1. 빈 입력 / 너무 짧음
    if not text:
        return FeasibilityResult(
            verdict=VERDICT_AMBIGUOUS,
            reason="입력이 비어있습니다",
            suggested_clarification="무엇을 도와드릴지 구체적으로 알려주세요.",
            decided_by="rule",
        )
    if len(text) < _MIN_LENGTH:
        return FeasibilityResult(
            verdict=VERDICT_AMBIGUOUS,
            reason="요청이 너무 짧아 의도를 파악하기 어렵습니다",
            suggested_clarification="어떤 문서나 작업을 원하시는지 더 자세히 알려주세요.",
            decided_by="rule",
        )

    # 2. 명확한 문서/앱 요청이 먼저 (개발 맥락 우선)
    for pattern, label in _POSSIBLE_PATTERNS:
        if re.search(pattern, text):
            return FeasibilityResult(
                verdict=VERDICT_POSSIBLE,
                reason=f"{label}으로 판정",
                suggested_clarification=None,
                decided_by="rule",
            )

    # 3. 범위 밖 패턴
    for pattern, label in _OUT_OF_SCOPE_PATTERNS:
        if re.search(pattern, text):
            return FeasibilityResult(
                verdict=VERDICT_OUT_OF_SCOPE,
                reason=f"{label}는 시스템 범위 밖입니다",
                suggested_clarification=None,
                decided_by="rule",
            )

    # 4. 순수 주문/구매 패턴
    for pattern, label in _PURE_ORDER_PATTERNS:
        if re.search(pattern, text):
            return FeasibilityResult(
                verdict=VERDICT_OUT_OF_SCOPE,
                reason=f"{label}는 시스템 범위 밖입니다",
                suggested_clarification=None,
                decided_by="rule",
            )

    # 5. 모호함 힌트
    for pattern in _AMBIGUOUS_PATTERNS:
        if re.search(pattern, text):
            return FeasibilityResult(
                verdict=VERDICT_AMBIGUOUS,
                reason="목표가 구체적이지 않습니다",
                suggested_clarification="어떤 주제로 문서를 작성하거나 어떤 앱을 만들고 싶으신지 알려주세요.",
                decided_by="rule",
            )

    return None


# ---------------------------------------------------------------------------
# 2단계 — LLM 기반 판정 (call_llm_json 사용)
# ---------------------------------------------------------------------------

_LLM_PROMPT_TEMPLATE = """\
당신은 AI 오케스트레이터의 처리 가능성 판정관입니다.
사용자 요청을 3가지로 분류하세요.

## 분류 기준

### possible
- 문서 산출물로 풀 수 있음 (사업계획서, 분석, 조사, 전략, 매뉴얼 등)
- 또는 앱/코드 산출물 (버그 수정, 기능 추가, 시스템 구축 등)

### out_of_scope
- 실시간 정보 (오늘 날씨, 지금 주가, 현재 뉴스)
- 물리 세계 조작 (주문, 예약, 택시 호출)
- 외부 계정 연동 (개인 이메일 읽기, 캘린더 확인)
- 창작 예술 (이미지/음악/영상 생성)
- 책임 자문 (법률 상담, 의료 진단, 투자 결정)
- 실시간 대화 상대 (게임, 잡담)

### ambiguous
- 목표가 불명확 ("뭐 시켜줘", "아무거나")
- 너무 짧거나 맥락 부족
- 어떤 산출물을 원하는지 모를 때

## 사용자 요청
{raw_input}

## 응답 형식
반드시 아래 JSON만 출력하세요. 다른 설명 없이 JSON만.

{{
  "verdict": "possible" 또는 "out_of_scope" 또는 "ambiguous",
  "reason": "판정 이유 (1-2문장, 한국어)",
  "suggested_clarification": "ambiguous일 때 사용자에게 되물을 구체적 문구 (아니면 null)"
}}
"""


def _llm_judge(raw_input: str) -> FeasibilityResult:
    """
    2단계 LLM 기반 판정 — call_llm_json 사용.

    OPENROUTER_API_KEY 없거나 호출/파싱 실패 시 ambiguous로 안전하게 반환.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return FeasibilityResult(
            verdict=VERDICT_AMBIGUOUS,
            reason="규칙으로 판정 불가 + LLM 판정 불가(API 키 없음)",
            suggested_clarification="어떤 문서를 작성하거나 어떤 앱을 만들고 싶으신지 더 구체적으로 알려주세요.",
            decided_by="fallback",
        )

    prompt = _LLM_PROMPT_TEMPLATE.format(raw_input=raw_input)

    data = call_llm_json(
        prompt=prompt,
        model=FEASIBILITY_MODEL,
        timeout=FEASIBILITY_TIMEOUT,
    )

    # call_llm_json이 None 반환 = 네트워크 실패 or 모든 재시도 파싱 실패
    if data is None or not isinstance(data, dict):
        return FeasibilityResult(
            verdict=VERDICT_AMBIGUOUS,
            reason="LLM 판정 실패",
            suggested_clarification="요청을 더 구체적으로 다시 입력해주세요.",
            decided_by="fallback",
        )

    verdict = data.get("verdict", VERDICT_AMBIGUOUS)
    if verdict not in _ALL_VERDICTS:
        verdict = VERDICT_AMBIGUOUS

    return FeasibilityResult(
        verdict=verdict,
        reason=data.get("reason", "LLM 판정"),
        suggested_clarification=data.get("suggested_clarification"),
        decided_by="llm",
    )


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def check_feasibility(raw_input: str) -> FeasibilityResult:
    """
    Phase 0.5 · 처리 가능성 판정 (공개 API).

    1단계 규칙 판정 → 판정 안 되면 2단계 LLM 판정.
    항상 FeasibilityResult를 반환. 예외 전파 없음.
    """
    rule_result = _rule_based_judge(raw_input)
    if rule_result is not None:
        return rule_result

    return _llm_judge(raw_input)
