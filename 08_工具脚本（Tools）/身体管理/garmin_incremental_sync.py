"""Garmin CN incremental sync for Body OS.

Refreshes only the recent window (default 14 days) and merges it into the
long-range raw mirror. Layering contract:

    Garmin API
      -> raw_garmin_365d.json         (raw mirror, append/refresh only, never hand-edited)
      -> body_os_dataset_365d.json    (cleaned Body OS dataset)
      -> body_os_today_energy.json / _energy_status.json  (runtime context for agents)

The raw mirror is NOT the business source of truth; derived layers must read
the cleaned dataset. meta.schema_version supports future field migrations.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any

from garmin_sync_365d import DAILY_DIMENSIONS, date_window, fetch_range

SCHEMA_VERSION = "1.0"
DEFAULT_RAW_PATH = Path(__file__).with_name("raw_garmin_365d.json")
DEFAULT_WINDOW_DAYS = 14
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

DAILY_KEYS = ["body_battery", *DAILY_DIMENSIONS.keys()]


def _item_date(item: Any) -> str | None:
    """Best-effort date extraction, including error entries."""
    if not isinstance(item, dict):
        return None
    for key in ("calendarDate", "date", "startDate", "startTimeLocal", "startTimeGMT"):
        value = item.get(key)
        if value:
            return str(value)[:10]
    dto = item.get("dailySleepDTO")
    if isinstance(dto, dict) and dto.get("calendarDate"):
        return str(dto["calendarDate"])[:10]
    params = item.get("params")
    if isinstance(params, dict):
        for key in ("calendarDate", "date", "startDate", "endDate"):
            if params.get(key):
                return str(params[key])[:10]
    path = item.get("path")
    if isinstance(path, str):
        match = _DATE_RE.search(path)
        if match:
            return match.group(0)
    return None


def merge_daily_items(
    old_items: Any, new_items: Any, window_dates: set[str]
) -> list[Any]:
    """Replace window days with fresh data; keep history outside the window.

    Undated old entries (usually stale errors) are dropped because the window
    refresh supersedes them.
    """
    merged: list[Any] = []
    for item in old_items if isinstance(old_items, list) else []:
        date = _item_date(item)
        if date is None or date in window_dates:
            continue
        merged.append(item)
    if isinstance(new_items, list):
        merged.extend(new_items)
    merged.sort(key=lambda entry: _item_date(entry) or "")
    return merged


def _activity_key(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    activity_id = item.get("activityId")
    if activity_id is not None:
        return f"id:{activity_id}"
    date = _item_date(item)
    name = item.get("activityName")
    if date or name:
        return f"fallback:{date}|{name}"
    return None


def merge_activities(old_items: Any, new_items: Any) -> list[Any]:
    """Dedupe by activityId; fresh items win on conflict."""
    merged: dict[str, Any] = {}
    for source in (old_items, new_items):
        for item in source if isinstance(source, list) else []:
            key = _activity_key(item)
            if key is None:
                continue
            merged[key] = item
    return sorted(merged.values(), key=lambda entry: _item_date(entry) or "")


def merge_raw(
    old_raw: dict[str, Any],
    new_raw: dict[str, Any],
    *,
    window_start: str,
    window_end: str,
    sync_time: str | None = None,
) -> dict[str, Any]:
    """Pure merge of a window refresh into the long-range raw mirror."""
    window_dates = set()
    cursor = dt.date.fromisoformat(window_start)
    end = dt.date.fromisoformat(window_end)
    while cursor <= end:
        window_dates.add(cursor.isoformat())
        cursor += dt.timedelta(days=1)

    merged = dict(old_raw)
    merged["activities"] = merge_activities(
        old_raw.get("activities"), new_raw.get("activities")
    )
    for key in DAILY_KEYS:
        merged[key] = merge_daily_items(
            old_raw.get(key), new_raw.get(key), window_dates
        )

    old_meta = old_raw.get("meta") if isinstance(old_raw.get("meta"), dict) else {}
    meta = dict(old_meta)
    starts = [value for value in (old_meta.get("start"), window_start) if value]
    meta.update(
        {
            "schema_version": SCHEMA_VERSION,
            "sync_time": sync_time
            or dt.datetime.now().isoformat(timespec="seconds"),
            "source": "garmin",
            "start": min(starts) if starts else window_start,
            "end": max(value for value in (old_meta.get("end"), window_end) if value),
            "last_incremental_window": {
                "start": window_start,
                "end": window_end,
            },
        }
    )
    merged["meta"] = meta
    return merged


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_remap(raw_path: Path) -> None:
    """Regenerate cleaned dataset + runtime context from the merged raw mirror."""
    import garmin_bodyos_365d as mapper

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    dataset = mapper.build_body_os_dataset(raw)
    dataset_out = raw_path.with_name("body_os_dataset_365d.json")
    summary_out = raw_path.with_name("body_os_garmin_summary.json")
    today_out = raw_path.with_name("body_os_today_energy.json")
    _write_json(dataset_out, dataset)
    _write_json(
        summary_out,
        {
            "source": dataset["source"],
            "date_range": dataset["date_range"],
            "summary": dataset["summary"],
            "today_energy_context": dataset.get("today_energy_context"),
            "today_training_context": dataset.get("today_training_context"),
        },
    )
    context = dataset.get("today_energy_context")
    _write_json(today_out, context or {})
    mapper.write_runtime_energy_status(mapper.DEFAULT_RUNTIME_ENERGY_STATUS, context)
    print(f"remap -> {dataset_out}")
    print(f"remap -> {summary_out}")
    print(f"remap -> {today_out}")
    print(f"remap -> {mapper.DEFAULT_RUNTIME_ENERGY_STATUS}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Incrementally sync recent Garmin CN data into the raw mirror."
    )
    parser.add_argument("--raw", default=str(DEFAULT_RAW_PATH))
    parser.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--email", default=os.environ.get("GARMIN_EMAIL"))
    parser.add_argument(
        "--skip-remap",
        action="store_true",
        help="Only refresh raw; skip regenerating cleaned dataset and runtime.",
    )
    args = parser.parse_args()

    raw_path = Path(args.raw)
    old_raw = json.loads(raw_path.read_text(encoding="utf-8"))

    from garmin_sync_7d import GarminCnGcApiClient

    start, end, _ = date_window(args.days)
    client = GarminCnGcApiClient(os.environ.get("GARMIN_CHROME_PROFILE"))
    try:
        new_raw = fetch_range(client, days=args.days, email=args.email)
    finally:
        client.close()

    merged = merge_raw(
        old_raw,
        new_raw,
        window_start=start.isoformat(),
        window_end=end.isoformat(),
    )
    _write_json(raw_path, merged)
    print(f"incremental window: {start} .. {end}")
    print(f"raw merged -> {raw_path}")
    for key in ("activities", *DAILY_KEYS):
        value = merged.get(key)
        count = len(value) if hasattr(value, "__len__") else "n/a"
        print(f"{key}: {count}")

    if not args.skip_remap:
        run_remap(raw_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
