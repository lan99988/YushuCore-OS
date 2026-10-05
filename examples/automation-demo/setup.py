"""Create a clean, isolated automation-demo config root."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


HERE = Path(__file__).resolve().parent


def _has_link(path: Path) -> bool:
    return any(item.is_symlink() or getattr(item, "is_junction", lambda: False)() for item in (path, *path.parents))


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir() or _has_link(source):
        raise ValueError("Demo source directories must be ordinary directories")
    for item in source.rglob("*"):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("Demo source must not contain linked paths")
    shutil.copytree(source, destination)


def _lock_plugin(root: Path, plugin: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "yushuos", "--config-root", str(root), "lock-plugin", "--path", str(plugin)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    lock_result = json.loads(result.stdout)
    if lock_result.get("status") != "succeeded" or lock_result.get("verified") is not True:
        raise RuntimeError("The installed Core did not verify the demo plugin lock")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an isolated, local-only automation demo root.")
    parser.add_argument("--root", type=Path, required=True, help="A new or empty directory dedicated to this demo")
    args = parser.parse_args()

    root = args.root.expanduser().absolute()
    if _has_link(root):
        raise SystemExit("Refusing a root that is a symlink, junction, or beneath one")
    if root.exists():
        if not root.is_dir() or any(root.iterdir()):
            raise SystemExit("Refusing to overwrite a non-empty demo root")
    else:
        root.parent.mkdir(parents=True, exist_ok=True)
        root.mkdir()

    (root / "plugins").mkdir()
    (root / "rules").mkdir()
    (root / "config.yaml").write_text((HERE / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "automation.yaml").write_text((HERE / "automation.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    plugin = root / "plugins" / "demo.counter"
    _copy_tree(HERE / "plugin", plugin)
    action_dir = root / "plugin-data" / "demo.counter" / "data" / "actions"
    action_dir.mkdir(parents=True)
    for action in ("create.json", "followup.json", "observe.json"):
        shutil.copyfile(HERE / "actions" / action, action_dir / action)
    for rule in ("create.json", "followup.json", "schedule.json"):
        shutil.copyfile(HERE / "rules" / rule, root / "rules" / rule)

    # Create an empty Core ledger through the public SDK connection API. The demo
    # owns this isolated ledger; it never opens the user's default Core root.
    from yushuos_sdk import StateStore
    ledger = root / "operations.sqlite3"
    with StateStore(ledger).connect(write=True):
        pass

    _lock_plugin(root, plugin)
    print("Created the isolated demo root. No external account, credential, or service is configured.")
    print("Rules are disabled. Review the generated files before enabling or granting any rule.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
