"""
v1 CLI — 5분류 + doc-only stop + resume from approved plan 지원.
"""
from __future__ import annotations

from src.orchestrator import (
    run_orchestration,
    create_packet_if_approved,
    save_execution_result_step,
    run_verification,
    finalize_run_step,
)
from src.approval.approval_service import apply_user_approval
from src.store.artifact_store import load_artifact


def _prompt(message: str) -> str:
    while True:
        value = input(message).strip()
        if value:
            return value
        print("빈 입력은 허용되지 않습니다.")


def _prompt_yes_no(message: str) -> bool:
    while True:
        v = input(message).strip().lower()
        if v in ("y", "yes", "예"):
            return True
        if v in ("n", "no", "아니오"):
            return False
        print("y/n 으로 응답하세요.")


def _prompt_approval() -> str:
    while True:
        decision = input("승인(approve) / 거절(reject): ").strip().lower()
        if decision in ("approve", "reject"):
            return decision
        print("approve 또는 reject만 입력하세요.")


def main() -> None:
    db_path = "orchestrator_v1.db"
    base_dir = "."

    # ── 모드 선택
    print("=== AI Orchestrator v1 ===")
    print("1. 새 요청")
    print("2. 기존 실행 재개 (resume)")
    mode = input("선택 (1/2): ").strip()

    if mode == "2":
        _resume_flow(db_path, base_dir)
        return

    # ── 새 요청
    user_input = _prompt("요청 입력: ")
    doc_only = _prompt_yes_no("문서 고정까지만 수행? (y/n): ")

    # ── 오케스트레이션 실행
    result = run_orchestration(user_input, db_path, doc_only=doc_only)

    _print_status(result)

    if result.get("task_type") == "unsupported":
        print("지원하지 않는 요청입니다.")
        return

    if result.get("run_status") == "doc_frozen":
        print("문서 고정 완료. 나중에 resume으로 계속할 수 있습니다.")
        print(f"  run_id: {result['run_id']}")
        return

    # ── 승인
    if result.get("approval_status") == "pending":
        _approval_flow(db_path, base_dir, result)


def _resume_flow(db_path: str, base_dir: str) -> None:
    """기존 run_id로부터 재개."""
    run_id = _prompt("run_id 입력: ")
    artifact = load_artifact(db_path, run_id=run_id)
    if not artifact:
        print(f"run_id '{run_id}'를 찾을 수 없습니다.")
        return

    _print_status(artifact)
    status = artifact.get("run_status", "")

    if status == "doc_frozen":
        print("문서 고정 상태 — 실행 계획으로 진행합니다.")
        from src.orchestrator import resume_from_doc
        updated = resume_from_doc(db_path, run_id)
        if updated:
            _print_status(updated)
            if updated.get("approval_status") == "pending":
                _approval_flow(db_path, base_dir, updated)
        return

    if status == "waiting_approval":
        _approval_flow(db_path, base_dir, artifact)
        return

    if status in ("approved", "packet_ready"):
        _post_approval_flow(db_path, base_dir, artifact)
        return

    if status == "execution_result_received":
        _verification_and_finalize(db_path, artifact)
        return

    print(f"현재 상태 '{status}'에서는 resume이 지원되지 않습니다.")


def _approval_flow(db_path: str, base_dir: str, artifact: dict) -> None:
    """승인 → 패킷 → 실행 → 검증 → finalize."""
    decision = _prompt_approval()
    run_id = artifact["run_id"]

    apply_user_approval(db_path, run_id, decision)

    if decision == "reject":
        print("승인 거절. 종료합니다.")
        return

    _post_approval_flow(db_path, base_dir, artifact)


def _post_approval_flow(db_path: str, base_dir: str, artifact: dict) -> None:
    """패킷 생성 → Cursor 실행 대기 → 결과 입력."""
    run_id = artifact["run_id"]
    goal = artifact.get("raw_input", "")

    packet = create_packet_if_approved(
        db_path=db_path,
        base_dir=base_dir,
        run_id=run_id,
        goal=goal,
        approval_status="approved",
    )

    print(f"\n패킷 생성: {packet['packet_created']}")
    print(f"패킷 경로: {packet['packet_path']}")
    print("위 파일을 Cursor Background Agent에 붙여넣고 실행하세요.\n")

    # 실행 결과 입력
    changed_files_input = _prompt("changed_files (쉼표 구분): ")
    test_results = _prompt("test_results: ")
    run_log = _prompt("run_log: ")

    changed_files = [f.strip() for f in changed_files_input.split(",") if f.strip()]

    save_execution_result_step(db_path, run_id, changed_files, test_results, run_log)

    # 검증 + finalize
    artifact_updated = load_artifact(db_path, run_id=run_id)
    _verification_and_finalize(db_path, artifact_updated or artifact)


def _verification_and_finalize(db_path: str, artifact: dict) -> None:
    """검증 → finalize."""
    run_id = artifact["run_id"]

    v = run_verification(db_path, run_id)
    print(f"\n검증 결과: {'통과' if v.get('all_passed') else '실패'}")

    if not v.get("all_passed"):
        alignment = v.get("spec_alignment", {})
        failure_type = alignment.get("failure_type", "")
        if failure_type == "slice_issue":
            print("→ slice 문제: task slice queue로 복귀 필요")
        elif failure_type == "doc_issue":
            print("→ doc 문제: cross-audit / canonical doc 재개정 필요")
        print("검증 실패. 수동으로 재시도하세요.")
        return

    exec_result = artifact.get("execution_result", {})
    summary = finalize_run_step(
        db_path=db_path,
        run_id=run_id,
        goal=artifact.get("raw_input", ""),
        approval_status="approved",
        changed_files=exec_result.get("changed_files", []),
        test_results=exec_result.get("test_results", ""),
        run_log=exec_result.get("run_log", ""),
    )

    print("\n" + "─" * 40)
    print(summary)
    print("─" * 40)


def _print_status(artifact: dict) -> None:
    print(f"\n  task_type      : {artifact.get('task_type')}")
    print(f"  run_status     : {artifact.get('run_status')}")
    print(f"  approval_status: {artifact.get('approval_status')}")
    print(f"  run_id         : {artifact.get('run_id')}")
    print(f"  thread_id      : {artifact.get('thread_id')}")
    print()


if __name__ == "__main__":
    main()
