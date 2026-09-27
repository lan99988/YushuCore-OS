from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capability_plugins.loader import load_manifests
from capability_plugins.registry import PluginRegistry


DEFAULT_MANIFEST_DIR = ROOT / "capability_plugins" / "manifests"


def collect_inventory(
    manifest_dir: str | Path = DEFAULT_MANIFEST_DIR,
) -> tuple[dict[str, object], ...]:
    """List plugin lifecycle state and declared capabilities without loading code."""
    manifests = load_manifests(manifest_dir)
    registry = PluginRegistry.from_manifests(manifests)
    return tuple(
        {
            "plugin_id": manifest.plugin_id,
            "name": manifest.name,
            "domain": manifest.domain,
            "status": registry.explain(manifest.plugin_id)["status"],
            "capabilities": list(sorted(manifest.provides)),
        }
        for manifest in sorted(manifests, key=lambda item: item.plugin_id)
    )


def health_summary(items: Iterable[dict[str, object]]) -> dict[str, int]:
    rows = tuple(items)
    return {
        "plugin_count": len(rows),
        "ready_count": sum(row["status"] == "ready" for row in rows),
        "unready_count": sum(row["status"] != "ready" for row in rows),
        "capability_count": sum(
            len(row["capabilities"])
            for row in rows
            if row["status"] == "ready"
        ),
    }


def _render_table(items: Iterable[dict[str, object]]) -> str:
    rows = [
        (
            str(item["plugin_id"]),
            str(item["status"]),
            str(item["domain"]),
            ", ".join(item["capabilities"]),
        )
        for item in items
    ]
    headers = ("plugin_id", "status", "domain", "capabilities")
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    lines = [" | ".join(headers[index].ljust(widths[index]) for index in range(4))]
    lines.append("-+-".join("-" * width for width in widths))
    lines.extend(
        " | ".join(row[index].ljust(widths[index]) for index in range(4))
        for row in rows
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="List plugin readiness and declared capabilities (offline)."
    )
    parser.add_argument("--manifests", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--format", choices=("table", "json"), default="table")
    args = parser.parse_args(argv)
    items = collect_inventory(args.manifests)
    if args.format == "json":
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        print(_render_table(items))


if __name__ == "__main__":
    main()
