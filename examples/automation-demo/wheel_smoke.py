"""Install a built wheel into a temporary target and smoke-test its installed CLI."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def _run(command: list[str], *, cwd: Path, env: dict[str, str], capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=capture,
        timeout=60,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel-dir", type=Path, required=True)
    args = parser.parse_args()
    wheels = sorted(args.wheel_dir.resolve().glob("yushuos_core-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Expected exactly one yushuos-core wheel")

    with tempfile.TemporaryDirectory(prefix="yushuos-wheel-smoke-") as temporary:
        root = Path(temporary)
        target = root / "installed"
        target.mkdir()
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--no-deps", "--target", str(target), str(wheels[0])],
            check=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(target)

        imported = _run(
            [sys.executable, "-c", "import json, yushuos; print(json.dumps({'version': yushuos.__version__, 'path': yushuos.__file__}))"],
            cwd=root,
            env=env,
            capture=True,
        )
        package = json.loads(imported.stdout)
        if not Path(package["path"]).resolve().is_relative_to(target.resolve()):
            raise SystemExit("Smoke test imported yushuos from outside the installed wheel")

        _run([sys.executable, "-m", "yushuos", "--help"], cwd=root, env=env, capture=True)
        _run([sys.executable, "-m", "yushuos", "automation", "--help"], cwd=root, env=env, capture=True)
        config_root = root / "private-core"
        config_root.mkdir()
        doctor = _run(
            [sys.executable, "-m", "yushuos", "--config-root", str(config_root), "doctor"],
            cwd=root,
            env=env,
            capture=True,
        )
        value = json.loads(doctor.stdout)
        if value.get("api_version") != 2 or value.get("config_root_available") is not True:
            raise SystemExit("Installed wheel doctor output is incomplete")

        print(f"Installed wheel smoke test passed ({package['version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
