"""Execution Packet Builder — 8필드 패킷 생성.

패킷 필드:
  run_id, goal, scope, target_files, forbidden_actions,
  completion_criteria, test_command, output_format
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExecutionPacket:
    """실행 패킷."""
    run_id:              str
    goal:                str
    scope:               str = ""
    target_files:        list[str] = field(default_factory=list)
    forbidden_actions:   list[str] = field(default_factory=list)
    completion_criteria: list[str] = field(default_factory=list)
    test_command:        str = "pytest -v"
    output_format:       str = "changed_files, test_results, run_log"

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "scope": self.scope,
            "target_files": self.target_files,
            "forbidden_actions": self.forbidden_actions,
            "completion_criteria": self.completion_criteria,
            "test_command": self.test_command,
            "output_format": self.output_format,
        }

    def to_markdown(self) -> str:
        target = "\n".join(f"- {f}" for f in self.target_files) if self.target_files else "- (미지정)"
        forbidden = "\n".join(f"- {f}" for f in self.forbidden_actions) if self.forbidden_actions else "- scope 이탈 금지"
        criteria = "\n".join(f"- {c}" for c in self.completion_criteria) if self.completion_criteria else "- 모든 테스트 통과"

        return f"""# Cursor Job Packet

## run_id
{self.run_id}

## goal
{self.goal}

## scope
{self.scope or '전체'}

## target_files
{target}

## forbidden_actions
{forbidden}

## completion_criteria
{criteria}

## test_command
```
{self.test_command}
```

## output_format
{self.output_format}
"""


def build_execution_packet(
    run_id: str,
    goal: str,
    scope: str = "",
    target_files: list[str] | None = None,
    forbidden_actions: list[str] | None = None,
    completion_criteria: list[str] | None = None,
    test_command: str = "pytest -v",
    deliverable_spec: dict | None = None,
) -> ExecutionPacket:
    """deliverable_spec에서 패킷 필드를 추출하여 패킷 생성."""
    spec = deliverable_spec or {}
    return ExecutionPacket(
        run_id=run_id,
        goal=goal,
        scope=scope or spec.get("scope", ""),
        target_files=target_files or spec.get("target_files", []),
        forbidden_actions=forbidden_actions or spec.get("constraints", ["scope 이탈 금지"]),
        completion_criteria=completion_criteria or spec.get("acceptance_criteria", ["모든 테스트 통과"]),
        test_command=test_command,
    )


def write_packet_file(base_dir: str, packet: ExecutionPacket) -> str:
    """패킷을 markdown 파일로 저장하고 경로 반환."""
    cursor_jobs_dir = Path(base_dir) / "cursor_jobs"
    cursor_jobs_dir.mkdir(parents=True, exist_ok=True)
    packet_path = cursor_jobs_dir / f"{packet.run_id}.md"
    packet_path.write_text(packet.to_markdown(), encoding="utf-8")
    return str(packet_path)
