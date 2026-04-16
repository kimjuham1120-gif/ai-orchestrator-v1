"""8필드 패킷 생성 테스트."""
from pathlib import Path
from src.packet.packet_builder import build_execution_packet, write_packet_file


def test_packet_has_8_fields():
    packet = build_execution_packet("run-1", "fix login")
    d = packet.to_dict()
    required = {"run_id", "goal", "scope", "target_files", "forbidden_actions",
                "completion_criteria", "test_command", "output_format"}
    assert required.issubset(d.keys())


def test_packet_from_deliverable_spec():
    spec = {
        "goal": "fix auth",
        "scope": "auth module",
        "target_files": ["src/auth.py"],
        "constraints": ["scope 이탈 금지"],
        "acceptance_criteria": ["테스트 통과"],
    }
    packet = build_execution_packet("run-2", "fix auth", deliverable_spec=spec)
    assert packet.scope == "auth module"
    assert "src/auth.py" in packet.target_files
    assert "scope 이탈 금지" in packet.forbidden_actions


def test_write_packet_file(tmp_path):
    packet = build_execution_packet("run-abc", "버그 수정")
    path = write_packet_file(str(tmp_path), packet)
    assert Path(path).exists()
    content = Path(path).read_text(encoding="utf-8")
    assert "run-abc" in content
    assert "버그 수정" in content


def test_packet_markdown_has_all_sections():
    packet = build_execution_packet("run-x", "test goal")
    md = packet.to_markdown()
    for section in ["run_id", "goal", "scope", "target_files",
                    "forbidden_actions", "completion_criteria",
                    "test_command", "output_format"]:
        assert f"## {section}" in md
