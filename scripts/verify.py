from __future__ import annotations

import subprocess
import sys
import shutil
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.boundary import phase3_agent_boundary_report
from scripts.health_check import check_config


def run(command: list[str]) -> None:
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> None:
    pytest_command = shutil.which("pytest")
    run(([pytest_command, "-q"] if pytest_command else [sys.executable, "-m", "pytest", "-q"]))
    run([sys.executable, "-m", "compileall", "-q", "runtime_core", "agents", "integrations", "knowledge_system", "personal_intelligence", "scripts"])
    schema_path = ROOT / "knowledge_system/schema/knowledge_node.schema.json"
    json.loads(schema_path.read_text(encoding="utf-8"))
    config = check_config(ROOT / "config")
    if config["network_mode"] != "OFF":
        raise SystemExit("default network mode must be OFF")
    boundary = phase3_agent_boundary_report()
    if not boundary.is_clean():
        raise SystemExit(f"agent boundary violations: {boundary.violation_count}")


if __name__ == "__main__":
    main()
