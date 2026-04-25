"""
src/research_v2/base.py — Deep Research 어댑터 추상 기반 (Phase 2 재구성)

4개 벤더의 Deep Research API를 공통 인터페이스로 추상화.

주요 클래스:
  - ResearchAdapter  : 모든 어댑터의 추상 기반
  - ResearchResult   : 1회 리서치 결과 (보고서 + 인용 + 메타)
  - ResearchCitation : 인용 1건 (URL, 제목, 스니펫)

설계 원칙:
  - 어댑터는 자체 API 형식 차이를 내부에서 흡수
  - 공통 인터페이스는 최소화 (research(query) → ResearchResult)
  - 실패 시 예외 전파 없음: ResearchResult.status = "failed"
  - 모든 어댑터는 is_available() 로 실행 전 가용성 체크
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 결과 스키마
# ---------------------------------------------------------------------------

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"   # 키 없음 / 비활성화 / 예산 초과 등


@dataclass
class ResearchCitation:
    """리서치 인용 1건."""
    url: str
    title: str = ""
    snippet: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"url": self.url, "title": self.title, "snippet": self.snippet}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResearchCitation":
        return cls(
            url=str(data.get("url", "")),
            title=str(data.get("title", "")),
            snippet=str(data.get("snippet", "")),
        )


@dataclass
class ResearchResult:
    """
    1회 Deep Research 결과.

    Attributes:
      adapter_name: 어댑터 식별자 (예: "perplexity_sonar_dr")
      status: success | failed | skipped
      report: 리서치 보고서 본문 (markdown)
      citations: 인용 소스 목록
      model: 실제 사용된 모델 ID
      duration_ms: 소요 시간 (밀리초)
      cost_usd: 추정 비용 (0 허용, 벤더별 정확도 다름)
      error: 실패 시 메시지
      raw_meta: 벤더별 원본 메타데이터 (디버깅용)
    """
    adapter_name: str
    status: str = STATUS_SKIPPED
    report: str = ""
    citations: List[ResearchCitation] = field(default_factory=list)
    model: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None
    raw_meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == STATUS_SUCCESS and bool(self.report)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_name": self.adapter_name,
            "status": self.status,
            "report": self.report,
            "citations": [c.to_dict() for c in self.citations],
            "model": self.model,
            "duration_ms": self.duration_ms,
            "cost_usd": round(self.cost_usd, 6),
            "error": self.error,
            "raw_meta": self.raw_meta,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResearchResult":
        return cls(
            adapter_name=str(data.get("adapter_name", "")),
            status=str(data.get("status", STATUS_SKIPPED)),
            report=str(data.get("report", "")),
            citations=[
                ResearchCitation.from_dict(c)
                for c in (data.get("citations") or [])
                if isinstance(c, dict)
            ],
            model=str(data.get("model", "")),
            duration_ms=int(data.get("duration_ms", 0) or 0),
            cost_usd=float(data.get("cost_usd", 0.0) or 0.0),
            error=data.get("error"),
            raw_meta=data.get("raw_meta") or {},
        )


# ---------------------------------------------------------------------------
# 어댑터 추상 기반
# ---------------------------------------------------------------------------

class ResearchAdapter(ABC):
    """
    Deep Research 어댑터 추상 기반.

    각 벤더(Perplexity/OpenAI/Gemini/Claude) 구현체가 상속.

    하위 클래스가 반드시 오버라이드:
      - name (class attribute): 고유 식별자
      - is_available() : 실행 가능 여부 (API 키 존재 등)
      - _do_research(query) : 실제 벤더 API 호출

    공통 로직은 research()에서 처리:
      - 가용성 체크 → skipped 반환
      - 예외 캐치 → failed 반환
      - 시간 측정
    """
    # 하위 클래스에서 반드시 설정
    name: str = "base"

    # 기본 타임아웃 (초) — 하위 클래스가 재정의 가능
    default_timeout: float = 300.0

    @abstractmethod
    def is_available(self) -> bool:
        """실행 가능 여부 (API 키 설정 등 체크). 하위 클래스가 구현."""
        raise NotImplementedError

    @abstractmethod
    def _do_research(self, query: str, timeout: float) -> ResearchResult:
        """
        실제 벤더 API 호출. 예외 발생 허용 — research()가 캐치함.
        반환 ResearchResult는 최소한 report/citations/model이 채워져야 함.
        """
        raise NotImplementedError

    def research(
        self,
        query: str,
        timeout: Optional[float] = None,
    ) -> ResearchResult:
        """
        공용 진입점 — 가용성 체크 + 예외 처리 + 시간 측정.

        실패해도 예외 전파 없음. ResearchResult.status 로 판정.
        """
        if not self.is_available():
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_SKIPPED,
                error="not_available (API key missing or disabled)",
            )

        if not query or not query.strip():
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                error="empty query",
            )

        effective_timeout = float(timeout or self.default_timeout)

        import time
        start = time.time()
        try:
            result = self._do_research(query.strip(), effective_timeout)
        except Exception as exc:
            duration_ms = int((time.time() - start) * 1000)
            return ResearchResult(
                adapter_name=self.name,
                status=STATUS_FAILED,
                duration_ms=duration_ms,
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
            )

        # 정상 경로에서도 duration_ms 측정 (어댑터가 직접 안 채워도 보장)
        # 어댑터가 이미 duration_ms 채웠으면 존중, 아니면 자동 측정값 사용
        if not result.duration_ms:
            result.duration_ms = int((time.time() - start) * 1000)

        # 정상 반환이지만 내용이 비어있으면 failed 취급
        if result.status == STATUS_SUCCESS and not result.report:
            result.status = STATUS_FAILED
            result.error = result.error or "empty report"

        return result
