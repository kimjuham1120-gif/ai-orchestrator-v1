import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from src.research.gemini_adapter import GeminiResearchAdapter

adapter = GeminiResearchAdapter()
print("is_available:", adapter.is_available())

if not adapter.is_available():
    print("ERROR: GEMINI_API_KEY 또는 GOOGLE_API_KEY가 .env에 없습니다.")
    sys.exit(1)

r = adapter.search("로그인 버그 수정 리서치")
print("error:", r.error)
print("claims:", len(r.claims))
for c in r.claims:
    print(f"  [{c.source}] {c.text[:80]}")
