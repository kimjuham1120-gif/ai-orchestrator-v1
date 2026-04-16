"""최종 요약 텍스트 생성."""
from __future__ import annotations


def build_final_summary(
    goal: str,
    approval_status: str,
    changed_files: list[str],
    test_results: str,
    run_log: str,
    final_status: str,
) -> str:
    changed_files_text = ", ".join(changed_files) if changed_files else "none"
    return (
        f"요청 요약: {goal}\n"
        f"승인 상태: {approval_status}\n"
        f"변경 파일: {changed_files_text}\n"
        f"테스트 결과: {test_results}\n"
        f"실행 로그 요약: {run_log}\n"
        f"최종 상태: {final_status}"
    )
