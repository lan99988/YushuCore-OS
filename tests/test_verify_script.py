from __future__ import annotations

import sys

from scripts import verify


def test_verify_runs_pytest_with_current_interpreter(monkeypatch):
    commands: list[list[str]] = []

    monkeypatch.setattr(verify, "run", commands.append)
    monkeypatch.setattr(
        verify,
        "check_config",
        lambda _path: {
            "network_mode": "OFF",
            "knowledge_mode": "external_read_only",
        },
    )

    class CleanBoundary:
        violation_count = 0

        @staticmethod
        def is_clean() -> bool:
            return True

    monkeypatch.setattr(verify, "phase3_agent_boundary_report", CleanBoundary)

    verify.main()

    assert commands[0] == [sys.executable, "-m", "pytest", "-q"]
    assert "capability_plugins" in commands[1]
    assert "orchestration" in commands[1]
    assert "experience_layer" in commands[1]
