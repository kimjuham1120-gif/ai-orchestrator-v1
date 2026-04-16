# ai-orchestrator-v1

문서고정 중심 상위 계층 + 역산 실행 구조의 AI 오케스트레이션 엔진.

## 설치

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
cp .env.example .env          # 환경변수 설정
```

## 실행

```bash
python -m src.cli
```

## 테스트

```bash
pytest -v
```

## 구조

```
사용자 입력 → classifier(5분류) → research router → evidence bundle
→ initial document → cross-audit loop → canonical freeze
→ deliverable spec → backward planner → task slice queue
→ builder → 3-layer review → approval gate
→ execution packet → Cursor manual execution
→ result verifier → spec alignment checker
→ more slices? → final summary
```
