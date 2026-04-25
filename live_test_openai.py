"""
라이브 테스트 #2: OpenAI web_search 모드.

비용 예상: 약 $0.02 ~ $0.10 (gpt-5.4 + web_search_preview)
실행:
  python live_test_openai.py
"""
import os
import sys
from pathlib import Path

def _load_env():
    env_path = Path(".env")
    if not env_path.exists():
        print("ERROR: .env 없음")
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

if not os.environ.get("OPENAI_API_KEY", "").strip():
    print("ERROR: OPENAI_API_KEY 비어있음")
    sys.exit(1)

print("=" * 70)
print("라이브 테스트 #2: OpenAI web_search")
print("=" * 70)

from src.research_v2.registry import get_adapter

adapter = get_adapter("openai", mode="web_search")
print(f"어댑터: {adapter.name}")
print(f"모드:   {adapter.mode}")
print(f"is_available: {adapter.is_available()}")
print()

query = "What are the three main stages of coffee roasting? Brief overview."
print(f"쿼리: {query}")
print()
print("호출 중... (30-90초 소요 예상)")
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
    print("response_id:", result.raw_meta.get("response_id"))
else:
    print(f"error: {result.error}")
    print()
    print("--- raw_meta ---")
    for k, v in (result.raw_meta or {}).items():
        print(f"  {k}: {v}")

print()
print("=" * 70)
if result.status == "success":
    print("✅ 성공")
else:
    print("❌ 실패")
print("=" * 70)
