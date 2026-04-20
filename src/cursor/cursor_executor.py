"""
Cursor Executor — Cursor Background Agent 자동 실행 계층.

Day 65~72: Cursor 수동 handoff → 자동 실행 전환.

실행 방식:
  CURSOR_AUTO_MODE=true 시:
    1. packet 내용을 Cursor Background Agent API에 POST
    2. job_id 수신 → polling으로 완료 대기
    3. 결과 반환 → cursor_result_adapter로 파싱

  CURSOR_AUTO_MODE=false (기본) 또는 자동 실행 실패 시:
    → 수동 fallback (기존 CLI 흐름 유지)

환경변수:
  CURSOR_AUTO_MODE          — "true" / "false" (기본: false)
  CURSOR_API_KEY            — Cursor Background Agent API 키
  CURSOR_API_BASE_URL       — 기본값: https://api.cursor.sh
  CURSOR_REPO_PATH          — 실행할 로컬 저장소 경로 (기본: 현재 디렉토리)
  CURSOR_EXECUTION_TIMEOUT  — polling 최대 대기 초 (기본: 600.0)
  CURSOR_POLL_INTERVAL      — polling 간격 초 (기본: 10.0)

동작 규칙:
  CURSOR_AUTO_MODE=false → is_auto_mode()=False, 자동 실행 안 함
  CURSOR_AUTO_MODE=true + key 없음 → CursorExecutorError 전파
  CURSOR_AUTO_MODE=true + 실행 실패 → CursorExecutorError 전파 (silent 금지)
  timeout 초과 → CursorTimeoutError 전파
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class CursorExecutorError(Exception):
    """Cursor 자동 실행 실패."""


class CursorTimeoutError(CursorExecutorError):
    """Cursor 실행 timeout."""


_DEFAULT_BASE_URL = "https://api.cursor.sh"
_DEFAULT_TIMEOUT = 600.0
_DEFAULT_POLL_INTERVAL = 10.0


@dataclass
class CursorExecutionResult:
    """Cursor 실행 결과 raw 데이터."""
    job_id: str
    status: str          # "completed" / "failed" / "timeout"
    output: str          # Agent 출력 전문
    changed_files: list[str]
    test_output: str
    error: Optional[str] = None


def is_auto_mode() -> bool:
    """CURSOR_AUTO_MODE=true 일 때만 자동 모드."""
    return os.environ.get("CURSOR_AUTO_MODE", "false").lower() == "true"


def get_cursor_api_key() -> Optional[str]:
    return os.environ.get("CURSOR_API_KEY")


class CursorExecutor:
    """Cursor Background Agent 자동 실행."""

    def __init__(self) -> None:
        self._api_key: Optional[str] = get_cursor_api_key()
        self._base_url: str = os.environ.get(
            "CURSOR_API_BASE_URL", _DEFAULT_BASE_URL
        ).rstrip("/")
        self._repo_path: str = os.environ.get("CURSOR_REPO_PATH", ".")
        self._timeout: float = float(
            os.environ.get("CURSOR_EXECUTION_TIMEOUT", _DEFAULT_TIMEOUT)
        )
        self._poll_interval: float = float(
            os.environ.get("CURSOR_POLL_INTERVAL", _DEFAULT_POLL_INTERVAL)
        )

    def execute(self, packet_path: str, run_id: str) -> CursorExecutionResult:
        """
        패킷 파일을 Cursor Background Agent에 실행 요청.

        packet_path: 실행할 패킷 파일 경로
        run_id: artifact run_id (추적용)
        반환: CursorExecutionResult
        예외: CursorExecutorError, CursorTimeoutError
        """
        if not self._api_key:
            raise CursorExecutorError(
                "CURSOR_API_KEY not set — 자동 실행 불가. "
                "CURSOR_AUTO_MODE=false로 수동 모드를 사용하세요."
            )

        packet_content = self._read_packet(packet_path)
        job_id = self._submit_job(packet_content, run_id)
        result = self._poll_until_done(job_id)
        return result

    def _read_packet(self, packet_path: str) -> str:
        path = Path(packet_path)
        if not path.exists():
            raise CursorExecutorError(f"패킷 파일 없음: {packet_path}")
        return path.read_text(encoding="utf-8")

    def _submit_job(self, packet_content: str, run_id: str) -> str:
        """Background Agent에 작업 제출 → job_id 반환."""
        import httpx

        url = f"{self._base_url}/v1/background-agent/jobs"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "instructions": packet_content,
            "repo_path": self._repo_path,
            "run_id": run_id,
            "metadata": {"orchestrator": "ai-orchestrator-v1"},
        }

        response = httpx.post(url, headers=headers, json=payload, timeout=30.0)
        response.raise_for_status()

        data = response.json()
        job_id = data.get("job_id") or data.get("id")
        if not job_id:
            raise CursorExecutorError(
                f"Cursor API가 job_id를 반환하지 않음: {data}"
            )
        return job_id

    def _poll_until_done(self, job_id: str) -> CursorExecutionResult:
        """job 완료까지 polling."""
        import httpx

        url = f"{self._base_url}/v1/background-agent/jobs/{job_id}"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        deadline = time.time() + self._timeout

        while True:
            if time.time() > deadline:
                raise CursorTimeoutError(
                    f"Cursor 실행 timeout ({self._timeout}s) — job_id={job_id}"
                )

            response = httpx.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            data = response.json()

            status = data.get("status", "pending")

            if status == "completed":
                return _parse_job_result(job_id, data)
            elif status == "failed":
                error_msg = data.get("error") or data.get("message") or "unknown error"
                raise CursorExecutorError(
                    f"Cursor 실행 실패 — job_id={job_id}: {error_msg}"
                )

            time.sleep(self._poll_interval)


def _parse_job_result(job_id: str, data: dict) -> CursorExecutionResult:
    """Cursor API 응답 → CursorExecutionResult."""
    output = data.get("output") or data.get("result") or ""
    changed_files = data.get("changed_files") or []
    test_output = data.get("test_output") or data.get("test_results") or ""

    # output에서 changed_files 파싱 (API가 직접 안 주는 경우)
    if not changed_files and output:
        changed_files = _extract_changed_files_from_output(output)

    if not test_output and output:
        test_output = _extract_test_output_from_output(output)

    return CursorExecutionResult(
        job_id=job_id,
        status="completed",
        output=output,
        changed_files=changed_files,
        test_output=test_output,
    )


def _extract_changed_files_from_output(output: str) -> list[str]:
    """output 텍스트에서 변경 파일 목록 추출."""
    files: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        # "modified: src/auth.py" 또는 "changed: src/auth.py" 패턴
        for prefix in ("modified:", "changed:", "edited:", "updated:", "M "):
            if line.lower().startswith(prefix.lower()):
                f = line[len(prefix):].strip()
                if f and ("." in f or "/" in f):
                    files.append(f)
    return files


def _extract_test_output_from_output(output: str) -> str:
    """output 텍스트에서 테스트 결과 추출."""
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if any(kw in line.lower() for kw in ("passed", "failed", "pytest", "test")):
            # 해당 줄부터 최대 5줄
            return "\n".join(lines[i:i+5]).strip()
    return output[:200] if output else ""
