"""
라이브 테스트 #1: Perplexity web_search 모드.

목적:
  - .env 의 PERPLEXITY_API_KEY 로 실제 호출 1회
  - 응답 구조가 mock과 일치하는지 검증
  - 비용/지연시간 측정

비용 예상: 약 $0.005 ~ $0.02 (sonar-pro, 짧은 쿼리)
실행:
  python live_test_perplexity.py
"""
import os
import sys
from pathlib import Path

# .env 로드 (python-dotenv가 있으면 사용, 없으면 수동 파싱)
def _load_env():
    env_path = Path(".env")
    if not env_path.exists():
        print("ERROR: .env 파일 없음")
        sys.exit(1)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value

_load_env()

# 키 확인
if not os.environ.get("PERPLEXITY_API_KEY", "").strip():
    print("ERROR: PERPLEXITY_API_KEY 비어있음")
    sys.exit(1)

print("=" * 70)
print("라이브 테스트 #1: Perplexity web_search")
print("=" * 70)

from src.research_v2.registry import get_adapter

adapter = get_adapter("perplexity", mode="web_search")
print(f"어댑터: {adapter.name}")
print(f"모드:   {adapter.mode}")
print(f"모델:   {adapter._config['model']}")
print(f"is_available: {adapter.is_available()}")
print()

query = "What are the three main stages of coffee roasting? Brief overview."
print(f"쿼리: {query}")
print()
print("호출 중... (10-30초 소요 예상)")
print()

result = adapter.research(query)

print("=" * 70)
print("결과")
print("=" * 70)
print(f"status:        {result.status}")
print(f"adapter_name:  {result.adapter_name}")
print(f"model:         {result.model}")
print(f"duration_ms:   {result.duration_ms}")
print(f"cost_usd:      ${result.cost_usd:.6f}")

if result.status == "success":
    print(f"citations:     {len(result.citations)}개")
    for i, cit in enumerate(result.citations[:3], 1):
        print(f"  [{i}] {cit.url}")
        if cit.title:
            print(f"      title: {cit.title[:80]}")

    print()
    print("--- 보고서 (앞 500자) ---")
    print(result.report[:500])
    print("--- 끝 ---")

    print()
    print("usage:", result.raw_meta.get("usage"))
else:
    print(f"error: {result.error}")

print()
print("=" * 70)
if result.status == "success":
    print("✅ 성공")
else:
    print("❌ 실패")
print("=" * 70)
