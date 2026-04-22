# 스냅샷 — ai-orchestrator-v3 (Day 97~104)

## 테스트 상태
```
목표: ~380 passed (343 기존 + ~37 신규)
신규: tests/test_day97_interpreter.py
```

## 신규 파일
```
src/interpreter/__init__.py
src/interpreter/request_interpreter.py  ← 자유 요청 해석
src/interpreter/flow_router.py          ← 복합 흐름 라우팅
src/web/app.py                          ← interpreter 연결 (수정)
tests/test_day97_interpreter.py         ← 신규 테스트
```

## 해석 계층 흐름
```
사용자 자유 입력
  → interpret_request(raw)
      1. 안전 검사 (unsafe → unsupported)
      2. 복합 규칙 매칭 (research+planning 등)
      3. 단일 규칙 매칭
      4. LLM fallback (INTERPRETER_USE_LLM=true)
      5. 기존 classifier fallback
      6. 개발 키워드 있으면 code_fix 유도
      7. 진짜 unsupported
  → route(interpreted, db_path)
      → resolve_flow() → task_type 결정
      → build_enriched_input() → raw_input 보강
      → run_orchestration() 재사용
```

## 지원 복합 조합
| capabilities | chosen_flow |
|---|---|
| research + code_fix | code_fix |
| research + planning | research |
| research + feature | feature |
| review + code_fix | code_fix |
| planning + review | review |
| research + planning + feature | feature |
| research + planning + build | feature |

## Classifier 관계
기존 `src/classifier/classifier.py` 유지.
interpreter가 해석 실패 시 fallback으로 사용.
삭제 없음.

## 환경변수 추가
```env
INTERPRETER_USE_LLM=false  # true 시 OpenRouter LLM 해석 사용
```
