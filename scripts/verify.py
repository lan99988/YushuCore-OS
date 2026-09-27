from __future__ import annotations

import subprocess
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.boundary import phase3_agent_boundary_report
from scripts.health_check import check_config, check_plugin_inventory


def run(command: list[str]) -> None:
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> None:
    run([sys.executable, "-m", "pytest", "-q"])
    run([sys.executable, "-m", "compileall", "-q", "runtime_core", "agents", "integrations", "knowledge_system", "personal_intelligence", "information_system", "cognitive_system", "capability_plugins", "orchestration", "experience_layer", "scripts"])
    schema_path = ROOT / "knowledge_system/schema/knowledge_node.schema.json"
    json.loads(schema_path.read_text(encoding="utf-8"))
    config = check_config(ROOT / "config")
    check_plugin_inventory(ROOT / "capability_plugins" / "manifests")
    if config["network_mode"] != "OFF":
        raise SystemExit("default network mode must be OFF")
    if config["knowledge_mode"] != "external_read_only":
        raise SystemExit("external knowledge base must remain read-only")
    boundary = phase3_agent_boundary_report()
    if not boundary.is_clean():
        raise SystemExit(f"agent boundary violations: {boundary.violation_count}")


if __name__ == "__main__":
    main()
