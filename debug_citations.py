"""
디버깅 #1: OpenAI + Gemini raw 응답에서 citation 위치 파악.

목적:
  - 실제 응답에 citation이 어느 필드에 있는지 출력
  - 우리 파서가 못 찾는 위치 발견

출력:
  - 응답 전체 구조 (depth=3까지)
  - "url" 또는 "uri"가 포함된 모든 경로
  - citations / sources / annotations 필드 발견 시 내용

비용: 약 $0.025
실행: python debug_citations.py
"""
import os
import sys
import json
from pathlib import Path

def _load_env():
    env_path = Path(".env")
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


def _walk_for_urls(obj, path=""):
    """응답 트리에서 url/uri 키를 가진 모든 경로 출력."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            if k.lower() in ("url", "uri", "link"):
                found.append((new_path, v))
            elif k.lower() in ("citations", "sources", "annotations", "grounding_chunks", "grounding_metadata"):
                preview = json.dumps(v, ensure_ascii=False)[:200]
                found.append((f"{new_path} (FIELD)", preview))
            found.extend(_walk_for_urls(v, new_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found.extend(_walk_for_urls(item, f"{path}[{i}]"))
    return found


def _print_structure(obj, indent=0, max_depth=4):
    """객체 구조 트리 출력 (값은 짧게)."""
    if indent > max_depth:
        return
    pad = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}: ({type(v).__name__}, len={len(v)})")
                _print_structure(v, indent + 1, max_depth)
            else:
                preview = str(v)[:80]
                print(f"{pad}{k}: {preview}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:5]):  # 처음 5개만
            print(f"{pad}[{i}]:")
            _print_structure(item, indent + 1, max_depth)
        if len(obj) > 5:
            print(f"{pad}... ({len(obj) - 5}개 더)")


# ===========================================================================
# OpenAI 디버깅
# ===========================================================================

def debug_openai():
    print("=" * 70)
    print("OpenAI Responses API — Raw 응답 디버깅")
    print("=" * 70)

    import httpx

    api_key = os.environ["OPENAI_API_KEY"].strip()
    payload = {
        "model": "gpt-5.4",
        "input": [
            {"role": "developer", "content": [{"type": "input_text",
                "text": "You are a research assistant. Cite all sources."}]},
            {"role": "user", "content": [{"type": "input_text",
                "text": "What are the three stages of coffee roasting? Brief, with sources."}]},
        ],
        "tools": [{"type": "web_search_preview"}],
    }

    print("호출 중... (30~90초)")
    response = httpx.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=300.0,
    )

    if response.status_code >= 400:
        print(f"❌ HTTP {response.status_code}: {response.text[:500]}")
        return

    body = response.json()

    print("\n--- 응답 최상위 키 ---")
    for k in body.keys():
        print(f"  {k}: ({type(body[k]).__name__})")

    print("\n--- output 배열 구조 ---")
    output = body.get("output", [])
    print(f"output 길이: {len(output)}")
    for i, item in enumerate(output):
        print(f"\n[{i}] type={item.get('type', 'unknown')}")
        _print_structure(item, indent=1, max_depth=4)

    print("\n--- url/uri/citations 필드 탐색 ---")
    found = _walk_for_urls(body)
    if not found:
        print("  ⚠️  url/uri 필드 없음 — 진짜 citation이 응답에 없음")
    for path, val in found[:30]:
        val_str = json.dumps(val, ensure_ascii=False)[:150] if isinstance(val, (dict, list)) else str(val)[:150]
        print(f"  {path}: {val_str}")


# ===========================================================================
# Gemini 디버깅
# ===========================================================================

def debug_gemini():
    print("\n\n" + "=" * 70)
    print("Gemini generateContent — Raw 응답 디버깅")
    print("=" * 70)

    import httpx

    api_key = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", "")).strip()
    model = "gemini-3.1-pro-preview"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    payload = {
        "contents": [{"role": "user",
                      "parts": [{"text": "What are the three stages of coffee roasting? Brief, with sources."}]}],
        "tools": [{"google_search": {}}],
        "systemInstruction": {"parts": [{"text": "Cite all sources."}]},
    }

    print("호출 중... (15~60초)")
    response = httpx.post(
        url,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=300.0,
    )

    if response.status_code >= 400:
        print(f"❌ HTTP {response.status_code}: {response.text[:500]}")
        return

    body = response.json()

    print("\n--- 응답 최상위 키 ---")
    for k in body.keys():
        print(f"  {k}: ({type(body[k]).__name__})")

    print("\n--- candidates[0] 구조 ---")
    candidates = body.get("candidates", [])
    if candidates:
        candidate = candidates[0]
        print(f"candidate 키: {list(candidate.keys())}")
        for k, v in candidate.items():
            if k == "content":
                continue  # content.parts는 텍스트라 스킵
            print(f"\n[{k}]:")
            _print_structure({k: v}, indent=1, max_depth=5)

    print("\n--- url/uri/citations 필드 탐색 ---")
    found = _walk_for_urls(body)
    if not found:
        print("  ⚠️  url/uri 필드 없음")
    for path, val in found[:30]:
        val_str = json.dumps(val, ensure_ascii=False)[:150] if isinstance(val, (dict, list)) else str(val)[:150]
        print(f"  {path}: {val_str}")


if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("OPENAI_API_KEY 없음")
        sys.exit(1)
    if not (os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()):
        print("GEMINI_API_KEY 없음")
        sys.exit(1)

    debug_openai()
    debug_gemini()

    print("\n" + "=" * 70)
    print("디버깅 완료. 위 결과에서 citations/url/grounding 위치를 확인하세요.")
    print("=" * 70)
