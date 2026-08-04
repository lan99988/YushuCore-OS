"""Garmin CN long-range raw data sync for Body OS.

This script uses the Garmin Web gc-api routes discovered from the CN site. It
stores raw sensor data only; business mapping can evolve separately.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from garmin_sync_7d import GarminCnGcApiClient, _filter_activities_by_date


DAILY_DIMENSIONS = {
    "daily_summary": lambda day, profile: (
        f"/usersummary-service/usersummary/daily/{profile}",
        {"calendarDate": day},
    ),
    "sleep": lambda day, profile: (
        f"/wellness-service/wellness/dailySleepData/{profile}",
        {"date": day},
    ),
    "heart_rate": lambda day, _profile: (
        "/wellness-service/wellness/dailyHeartRate",
        {"date": day},
    ),
    "stress": lambda day, _profile: (
        f"/wellness-service/wellness/dailyStress/{day}",
        None,
    ),
    "respiration": lambda day, _profile: (
        f"/wellness-service/wellness/daily/respiration/{day}",
        None,
    ),
    "spo2": lambda day, _profile: (
        f"/wellness-service/wellness/daily/spo2acclimation/{day}",
        None,
    ),
    "hrv": lambda day, _profile: (f"/hrv-service/hrv/{day}", None),
    "training_readiness": lambda day, _profile: (
        f"/metrics-service/metrics/trainingreadiness/{day}",
        None,
    ),
    "training_status": lambda day, _profile: (
        f"/metrics-service/metrics/trainingstatus/daily/{day}",
        None,
    ),
}


def date_window(
    days: int, *, today: dt.date | None = None
) -> tuple[dt.date, dt.date, list[str]]:
    if days < 1:
        raise ValueError("days must be >= 1")
    end = today or dt.date.today()
    start = end - dt.timedelta(days=days - 1)
    values = [(start + dt.timedelta(days=offset)).isoformat() for offset in range(days)]
    return start, end, values


def _safe_gc_api(client: Any, path: str, params: dict[str, Any] | None = None) -> Any:
    try:
        return client.gc_api(path, params)
    except Exception as exc:
        return {
            "error": type(exc).__name__,
            "message": str(exc)[:300],
            "path": path,
            "params": params or {},
        }


def fetch_activities(
    client: Any,
    *,
    start: dt.date,
    end: dt.date,
    page_size: int = 100,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for page_index in range(max_pages):
        offset = page_index * page_size
        page = _safe_gc_api(
            client,
            "/activitylist-service/activities/search/activities",
            {"start": str(offset), "limit": str(page_size)},
        )
        if not isinstance(page, list) or not page:
            break
        collected.extend(_filter_activities_by_date(page, start, end))
        dates = [
            item.get("startTimeLocal") or item.get("startTimeGMT")
            for item in page
            if isinstance(item, dict)
        ]
        parsed_dates = []
        for value in dates:
            if not value:
                continue
            try:
                parsed_dates.append(dt.date.fromisoformat(str(value)[:10]))
            except ValueError:
                continue
        if parsed_dates and min(parsed_dates) < start:
            break
        if len(page) < page_size:
            break
    return collected


def fetch_body_battery(
    client: Any,
    *,
    start: dt.date,
    end: dt.date,
    chunk_days: int = 14,
) -> list[dict[str, Any]]:
    if chunk_days < 1:
        raise ValueError("chunk_days must be >= 1")
    values: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + dt.timedelta(days=chunk_days - 1))
        chunk = _safe_gc_api(
            client,
            "/wellness-service/wellness/bodyBattery/reports/daily",
            {"startDate": cursor.isoformat(), "endDate": chunk_end.isoformat()},
        )
        if isinstance(chunk, list):
            values.extend(chunk)
        else:
            values.append(chunk)
        cursor = chunk_end + dt.timedelta(days=1)
    return values


def fetch_range(
    client: Any,
    *,
    days: int = 365,
    today: dt.date | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    start, end, day_values = date_window(days, today=today)
    profile = client.display_name()
    raw: dict[str, Any] = {
        "meta": {
            "account": email,
            "source": "garmin_cn_gc_api_365d",
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": days,
            "dimensions": [
                "activities",
                "body_battery",
                *DAILY_DIMENSIONS.keys(),
            ],
        },
        "activities": fetch_activities(client, start=start, end=end),
        "body_battery": fetch_body_battery(client, start=start, end=end),
    }

    for name, build in DAILY_DIMENSIONS.items():
        items = []
        for day in day_values:
            path, params = build(day, profile)
            items.append(_safe_gc_api(client, path, params))
        raw[name] = items
    return raw


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Garmin CN long-range raw data.")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--email", default=os.environ.get("GARMIN_EMAIL"))
    parser.add_argument("--out", default="raw_garmin_365d.json")
    args = parser.parse_args()

    client = GarminCnGcApiClient(os.environ.get("GARMIN_CHROME_PROFILE"))
    try:
        raw = fetch_range(client, days=args.days, email=args.email)
    finally:
        client.close()

    out = Path(args.out)
    _write_json(out, raw)
    print(f"raw_garmin_{args.days}d.json -> {out}")
    for key in ["activities", "body_battery", *DAILY_DIMENSIONS.keys()]:
        value = raw.get(key)
        count = len(value) if hasattr(value, "__len__") else "n/a"
        print(f"{key}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
