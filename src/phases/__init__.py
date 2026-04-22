"""
v4 Phase 패키지 — 7-Phase + Phase 0.5 워크플로우.

각 Phase는 독립된 모듈로 분리:
  - phase_0_5_gate.py     처리 가능성 게이트
  - phase_1_decompose.py  서브주제 분해 (다음 Step)
  - phase_2_research.py   병렬 리서치
  - phase_3_synthesize.py 2문서 합성
  - phase_4_audit.py      AI 교차 감사
  - phase_5_feedback.py   사용자 검수 루프
  - phase_6_bridge.py     트랙 전환 결정
  - phase_7_app_dev.py    앱개발 실행 (기존 v3 로직 호출 래퍼)
"""
