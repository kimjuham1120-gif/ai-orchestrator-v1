"""
라이브 테스트 #4: 4개 어댑터 병렬 호출.

목적:
  - run_parallel_research()가 실제 환경에서 ThreadPoolExecutor로 동작하는지 검증
  - 어댑터들이 동시에 호출되어 가장 느린 한 곳이 전체를 막지 않는지
  - skipped/failed/success 집계가 정확한지

비용 예상: 약 $0.025 ~ $0.05 (Perplexity + OpenAI + Gemini, Claude는 키 없으면 skipped)
실행:
  python live_test_parallel.py
"""
import os
import sys
import time
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

print("=" * 70)
print("라이브 테스트 #4: 4개 어댑터 병렬 호출")
print("=" * 70)

# 사용 가능한 키 표시
keys_status = {
    "PERPLEXITY": bool(os.environ.get("PERPLEXITY_API_KEY", "").strip()),
    "OPENAI": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
    "GEMINI": bool(os.environ.get("GEMINI_API_KEY", "").strip())
              or bool(os.environ.get("GOOGLE_API_KEY", "").strip()),
    "ANTHROPIC": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
}

print()
print("API 키 상태:")
for name, has_key in keys_status.items():
    mark = "✅" if has_key else "⚪ (skipped)"
    print(f"  {name}: {mark}")

available_count = sum(keys_status.values())
print(f"\n총 호출 어댑터: {available_count}개 (나머지는 skipped)")
print()

from src.research_v2.registry import build_default_adapters
from src.research_v2.parallel_runner import run_parallel_research

adapters = build_default_adapters(mode="web_search")
print(f"빌드된 어댑터: {len(adapters)}개")
for a in adapters:
    print(f"  - {a.name}")
print()

query = "What are the three main stages of coffee roasting? Brief overview."
print(f"쿼리: {query}")
print()
print("=" * 70)
print("병렬 호출 시작...")
print("(가장 느린 어댑터의 시간만큼만 걸려야 정상 — 직렬이면 합)")
print("=" * 70)

t0 = time.time()
parallel = run_parallel_research(adapters, query)
elapsed = time.time() - t0

print()
print("=" * 70)
print("결과")
print("=" * 70)
print(f"실측 elapsed:    {elapsed:.2f}초")
print(f"reported total:  {parallel.total_duration_ms}ms")
print()
print(f"전체 어댑터:     {len(parallel.results)}개")
print(f"성공:           {parallel.success_count}")
print(f"실패:           {parallel.failed_count}")
print(f"스킵:           {parallel.skipped_count}")
print(f"총 비용:         ${parallel.total_cost_usd:.6f}")
print()
print(f"has_success: {parallel.has_success}")
print(f"all_failed:  {parallel.all_failed}")
print()

print("--- 어댑터별 결과 ---")
for r in parallel.results:
    status_icon = {"success": "✅", "failed": "❌", "skipped": "⚪"}.get(r.status, "?")
    print(f"\n{status_icon} {r.adapter_name} [{r.status}]")
    print(f"   model: {r.model}")
    if r.status == "success":
        print(f"   cost:  ${r.cost_usd:.6f}")
        print(f"   citations: {len(r.citations)}개")
        report_preview = (r.report or "").strip().replace("\n", " ")[:120]
        print(f"   report (앞 120자): {report_preview}")
    elif r.status == "failed":
        print(f"   error: {r.error}")
    elif r.status == "skipped":
        print(f"   reason: API 키 없음")

print()
print("=" * 70)

# 검증
expected_callable = available_count
expected_skipped = 4 - available_count

if parallel.success_count + parallel.failed_count == expected_callable \
   and parallel.skipped_count == expected_skipped:
    print(f"✅ 카운트 일치 (호출 {expected_callable}개, 스킵 {expected_skipped}개)")
else:
    print(f"⚠️  카운트 불일치 (예상 호출 {expected_callable}, 스킵 {expected_skipped})")

if parallel.has_success:
    print("✅ 최소 1개 어댑터 성공 → Phase 2 진행 가능 상태")
else:
    print("❌ 모든 호출 실패 → Phase 2 차단 (AllSubtopicsFailedError)")

print("=" * 70)
