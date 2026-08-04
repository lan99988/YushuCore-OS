"""Map Garmin CN long-range raw data into Body OS project datasets."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from garmin_sync_7d import (
    _activity_type,
    _meters_to_km,
    _normalize_sleep,
    _readiness_score,
    _seconds_to_hours,
    _seconds_to_minutes,
    _sleep_score,
    _to_date,
    decide_today_focus,
)
from energy_policy import derive_daily_mental_state
from training_policy import derive_training_policy

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Fallback only. The single source of truth is body_os_config.json.
_FALLBACK_VALID_START = "2025-12-11"
DEFAULT_VALID_START = _FALLBACK_VALID_START
BODY_OS_CONFIG_PATH = (
    PROJECT_ROOT
    / "04_数据中心（Data）"
    / "系统配置（Config）"
    / "body_os_config.json"
)
_UNSET = object()


def load_body_os_config(path: Path | None = None) -> dict[str, Any]:
    """Load Body OS config. Returns {} when the file is missing or invalid."""
    config_path = path or BODY_OS_CONFIG_PATH
    try:
        payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_valid_start(config: dict[str, Any] | None = None) -> str:
    """Resolve the valid statistics start date from config, with fallback."""
    if config is None:
        config = load_body_os_config()
    body_data = config.get("body_data")
    if isinstance(body_data, dict):
        value = body_data.get("valid_start")
        if isinstance(value, str) and value:
            return value
    return _FALLBACK_VALID_START

DEFAULT_TODAY_ENERGY_OUT = Path(__file__).with_name("body_os_today_energy.json")
DEFAULT_RUNTIME_ENERGY_STATUS = (
    PROJECT_ROOT
    / "04_数据中心（Data）"
    / "运行状态（Runtime）"
    / "_energy_status.json"
)


def build_today_energy_context(
    dataset: dict[str, Any], *, today: str | None = None
) -> dict[str, Any] | None:
    energy_daily = [
        item
        for item in dataset.get("energy_daily", [])
        if isinstance(item, dict) and item.get("date")
    ]
    if not energy_daily:
        return None
    requested_date = today or dataset.get("date_range", {}).get("end")
    latest = sorted(energy_daily, key=lambda item: item["date"])[-1]
    context = dict(latest)
    context.update(derive_daily_mental_state(latest))
    context["source"] = context.get("source") or dataset.get("source")
    context["requested_date"] = requested_date
    context["is_requested_date"] = latest.get("date") == requested_date
    context["excluded_no_data_days"] = dataset.get("calibration", {}).get(
        "excluded_no_data_days", 0
    )
    return context


def runtime_energy_status(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": context.get("requested_date") or context.get("date"),
        "status": context.get("status"),
        "raw": f"Garmin最新有效日 {context.get('date')}：{context.get('reason')}",
        "source": "garmin",
        "garmin_date": context.get("date"),
        "is_requested_date": context.get("is_requested_date"),
        "level": context.get("level"),
        "mental_state": context.get("mental_state"),
        "mental_state_label": context.get("mental_state_label"),
        "study_load": context.get("study_load"),
        "study_load_label": context.get("study_load_label"),
        "task_policy": context.get("task_policy"),
        "energy_coefficient": context.get("energy_coefficient"),
        "body_battery": context.get("body_battery"),
        "body_battery_score": context.get(
            "body_battery_score", context.get("body_battery")
        ),
        "readiness_score": context.get("readiness_score"),
        "sleep_hours": context.get("sleep_hours"),
        "stress_level": context.get("stress_level"),
    }


def _valid_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and "error" not in item]


def _by_date(items: Any, *date_keys: str, normalizer=None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in _valid_items(items):
        if normalizer:
            item = normalizer(item)
        for key in date_keys:
            date = _to_date(item.get(key))
            if date:
                result[date] = item
                break
    return result


def _hrv_value(item: dict[str, Any] | None) -> Any:
    if not item:
        return None
    summary = item.get("hrvSummary")
    if isinstance(summary, dict):
        return (
            summary.get("lastNightAvg")
            or summary.get("weeklyAvg")
            or summary.get("lastNightAverage")
        )
    return item.get("lastNightAvg") or item.get("hrv_ms")


def _normalize_hrv(item: dict[str, Any]) -> dict[str, Any]:
    summary = item.get("hrvSummary")
    if isinstance(summary, dict):
        merged = dict(item)
        merged.update(summary)
        return merged
    return item


def _body_battery_value(item: dict[str, Any] | None, daily: dict[str, Any] | None) -> Any:
    if daily:
        value = (
            daily.get("bodyBatteryMostRecentValue")
            or daily.get("bodyBatteryHighestValue")
            or daily.get("bodyBatteryAtWakeTime")
        )
        if value is not None:
            return value
    if not item:
        return None
    return item.get("bodyBattery") or item.get("value") or item.get("charged")


def _numeric_values(values: list[Any]) -> list[float]:
    nums = []
    for value in values:
        if value is None:
            continue
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    return nums


def _average(values: list[Any]) -> float | None:
    nums = _numeric_values(values)
    if not nums:
        return None
    return round(sum(nums) / len(nums), 2)


def _map_training_logs(activities: Any) -> list[dict[str, Any]]:
    logs = []
    for activity in _valid_items(activities):
        logs.append(
            {
                "date": _to_date(
                    activity.get("startTimeLocal") or activity.get("startTimeGMT")
                ),
                "activity_type": _activity_type(activity),
                "session_name": activity.get("activityName"),
                "duration_min": _seconds_to_minutes(activity.get("duration")),
                "distance_km": _meters_to_km(activity.get("distance")),
                "avg_hr": activity.get("averageHR") or activity.get("avg_hr"),
                "training_load": activity.get("trainingLoad")
                or activity.get("activityTrainingLoad")
                or activity.get("training_load"),
                "garmin_activity_id": str(activity.get("activityId") or ""),
                "source": "garmin",
            }
        )
    return [log for log in logs if log.get("date")]


def _on_or_after(date: str | None, valid_start: str | None) -> bool:
    return bool(date) and (not valid_start or str(date) >= valid_start)


def _has_day_statistics(
    *,
    daily: dict[str, Any],
    sleep: dict[str, Any],
    heart: dict[str, Any],
    stress: dict[str, Any],
    battery: dict[str, Any],
    hrv: dict[str, Any],
    activity_count: int,
) -> bool:
    daily_signal = any(
        [
            (daily.get("totalSteps") or 0) > 0,
            (daily.get("activeKilocalories") or 0) > 0,
            (daily.get("moderateIntensityMinutes") or 0) > 0,
            (daily.get("vigorousIntensityMinutes") or 0) > 0,
            (daily.get("floorsAscended") or 0) > 0,
            (daily.get("floorsDescended") or 0) > 0,
            daily.get("averageStressLevel") not in (None, -1),
            daily.get("restingHeartRate") is not None,
            daily.get("bodyBatteryMostRecentValue") is not None,
            daily.get("averageSpo2") is not None,
        ]
    )
    sleep_signal = (
        sleep.get("sleepTimeSeconds") is not None and sleep.get("sleepTimeSeconds") != 0
    )
    heart_signal = heart.get("restingHeartRate") is not None
    stress_signal = stress.get("avgStressLevel") not in (None, -1)
    battery_signal = any(
        value is not None
        for value in (
            battery.get("charged"),
            battery.get("drained"),
            battery.get("bodyBatteryMostRecentValue"),
        )
    )
    hrv_signal = _hrv_value(hrv) is not None
    return any(
        [
            daily_signal,
            sleep_signal,
            heart_signal,
            stress_signal,
            battery_signal,
            hrv_signal,
            activity_count > 0,
        ]
    )


def build_body_os_dataset(
    raw: dict[str, Any], *, valid_start: str | None = _UNSET
) -> dict[str, Any]:
    if valid_start is _UNSET:
        valid_start = resolve_valid_start()
    daily_by_date = _by_date(raw.get("daily_summary"), "calendarDate", "date")
    sleep_by_date = _by_date(
        raw.get("sleep"), "calendarDate", "date", normalizer=_normalize_sleep
    )
    heart_by_date = _by_date(raw.get("heart_rate"), "calendarDate", "date")
    stress_by_date = _by_date(raw.get("stress"), "calendarDate", "date")
    battery_by_date = _by_date(raw.get("body_battery"), "calendarDate", "date")
    hrv_by_date = _by_date(
        raw.get("hrv"), "calendarDate", "date", normalizer=_normalize_hrv
    )
    all_training_logs = _map_training_logs(raw.get("activities"))
    activity_counts_by_date = Counter(
        item.get("date") for item in all_training_logs if item.get("date")
    )

    all_dates = sorted(
        set(daily_by_date)
        | set(sleep_by_date)
        | set(heart_by_date)
        | set(stress_by_date)
        | set(battery_by_date)
        | set(hrv_by_date)
        | set(activity_counts_by_date)
    )
    dates = [date for date in all_dates if _on_or_after(date, valid_start)]

    energy_daily = []
    body_metrics = []
    daily_wellness = []
    kept_dates: list[str] = []
    for date in dates:
        daily = daily_by_date.get(date, {})
        sleep = sleep_by_date.get(date, {})
        heart = heart_by_date.get(date, {})
        stress = stress_by_date.get(date, {})
        battery = battery_by_date.get(date, {})
        hrv = hrv_by_date.get(date, {})
        activity_count = activity_counts_by_date.get(date, 0)
        if not _has_day_statistics(
            daily=daily,
            sleep=sleep,
            heart=heart,
            stress=stress,
            battery=battery,
            hrv=hrv,
            activity_count=activity_count,
        ):
            continue
        kept_dates.append(date)
        resting_hr = (
            heart.get("restingHeartRate")
            or daily.get("restingHeartRate")
            or daily.get("lastSevenDaysAvgRestingHeartRate")
        )
        stress_level = stress.get("avgStressLevel") or daily.get("averageStressLevel")
        if stress_level == -1:
            stress_level = None
        energy = {
            "date": date,
            "sleep_hours": _seconds_to_hours(
                sleep.get("sleepTimeSeconds")
                or sleep.get("duration")
                or daily.get("sleepingSeconds")
            ),
            "sleep_quality": _sleep_score(sleep),
            "soreness": None,
            "stress_level": stress_level,
            "resting_hr": resting_hr,
            "hrv_ms": _hrv_value(hrv),
            # body_battery_score 是正式字段（身体可用能量）；body_battery 为兼容别名。
            "body_battery": _body_battery_value(battery, daily),
            "source": "garmin",
        }
        energy["body_battery_score"] = energy["body_battery"]
        energy["readiness_score"] = _readiness_score(energy)
        energy["recovery_note"] = decide_today_focus({"energy": energy})["recommendation"]
        energy.update(derive_daily_mental_state(energy))
        energy_daily.append(energy)

        body_metrics.append(
            {
                "date": date,
                "weight_kg": None,
                "body_fat_percent": None,
                "resting_hr": resting_hr,
                "hrv_ms": energy["hrv_ms"],
                "source": "garmin",
                "notes": "Garmin 365d sync",
            }
        )

        daily_wellness.append(
            {
                "date": date,
                "steps": daily.get("totalSteps"),
                "calories_total": daily.get("totalKilocalories"),
                "active_kcal": daily.get("activeKilocalories"),
                "moderate_intensity_min": daily.get("moderateIntensityMinutes"),
                "vigorous_intensity_min": daily.get("vigorousIntensityMinutes"),
                "floors_ascended": daily.get("floorsAscended"),
                "average_spo2": daily.get("averageSpo2"),
                "source": "garmin",
            }
        )

    training_logs = [
        item
        for item in all_training_logs
        if _on_or_after(item.get("date"), valid_start)
        and item.get("date") in kept_dates
    ]
    raw_start = raw.get("meta", {}).get("start")
    raw_end = raw.get("meta", {}).get("end")
    start_candidates = [
        value for value in [raw_start, valid_start, dates[0] if dates else None] if value
    ]
    effective_start = max(start_candidates) if start_candidates else None
    dataset = {
        "source": "garmin",
        "date_range": {
            "start": effective_start,
            "end": raw_end or (dates[-1] if dates else None),
            "raw_start": raw_start,
            "valid_start": valid_start,
        },
        "energy_daily": energy_daily,
        "training_logs": training_logs,
        "body_metrics": body_metrics,
        "daily_wellness": daily_wellness,
        "calibration": {
            "valid_start": valid_start,
            "reason": (
                f"Garmin 有效统计自 {valid_start} 开始（来源 body_os_config.json），"
                "之前数据不进入 Body OS 统计口径。"
                if valid_start
                else "未配置有效起点，全部日期进入统计。"
            ),
            "excluded_before_valid_start_days": len(all_dates) - len(dates),
            "excluded_no_data_days": len(dates) - len(kept_dates),
        },
    }
    dataset["summary"] = summarize_dataset(dataset)
    dataset["today_energy_context"] = build_today_energy_context(
        dataset, today=dataset["date_range"]["end"]
    )
    dataset["today_training_context"] = derive_training_policy(
        training_logs,
        today=dataset["date_range"]["end"],
        energy_context=dataset.get("today_energy_context"),
    )
    return dataset


def summarize_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    energy_daily = dataset.get("energy_daily", [])
    training_logs = dataset.get("training_logs", [])
    daily_wellness = dataset.get("daily_wellness", [])
    activity_counts = Counter(
        item.get("activity_type") for item in training_logs if item.get("activity_type")
    )
    return {
        "energy_days": len(energy_daily),
        "observation_days": len(energy_daily),
        "excluded_before_valid_start_days": dataset.get("calibration", {}).get(
            "excluded_before_valid_start_days", 0
        ),
        "excluded_no_data_days": dataset.get("calibration", {}).get(
            "excluded_no_data_days", 0
        ),
        "training_log_count": len(training_logs),
        "activity_type_counts": dict(sorted(activity_counts.items())),
        "avg_sleep_hours": _average([item.get("sleep_hours") for item in energy_daily]),
        "avg_readiness_score": _average(
            [item.get("readiness_score") for item in energy_daily]
        ),
        "avg_stress_level": _average([item.get("stress_level") for item in energy_daily]),
        "avg_resting_hr": _average([item.get("resting_hr") for item in energy_daily]),
        "avg_body_battery": _average(
            [item.get("body_battery") for item in energy_daily]
        ),
        "avg_body_battery_score": _average(
            [
                item.get("body_battery_score", item.get("body_battery"))
                for item in energy_daily
            ]
        ),
        "avg_steps": _average([item.get("steps") for item in daily_wellness]),
        "total_distance_km": round(
            sum(_numeric_values([item.get("distance_km") for item in training_logs])), 2
        ),
        "total_duration_min": round(
            sum(_numeric_values([item.get("duration_min") for item in training_logs])), 1
        ),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_runtime_energy_status(path: Path, context: dict[str, Any] | None) -> None:
    if not context:
        return
    _write_json(path, runtime_energy_status(context))


def main() -> int:
    parser = argparse.ArgumentParser(description="Map Garmin 365d raw data to Body OS.")
    parser.add_argument("--raw-input", required=True)
    parser.add_argument("--out", default="body_os_dataset_365d.json")
    parser.add_argument("--summary-out", default=None)
    parser.add_argument("--today-out", default=str(DEFAULT_TODAY_ENERGY_OUT))
    parser.add_argument(
        "--runtime-energy-out",
        default=str(DEFAULT_RUNTIME_ENERGY_STATUS),
    )
    args = parser.parse_args()

    raw = json.loads(Path(args.raw_input).read_text(encoding="utf-8"))
    dataset = build_body_os_dataset(raw)
    out = Path(args.out)
    _write_json(out, dataset)
    summary_out = Path(args.summary_out) if args.summary_out else out.with_name("body_os_garmin_summary.json")
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
    if args.today_out:
        _write_json(Path(args.today_out), dataset.get("today_energy_context") or {})
    if args.runtime_energy_out:
        write_runtime_energy_status(
            Path(args.runtime_energy_out), dataset.get("today_energy_context")
        )
    print(f"body_os_dataset_365d.json -> {out}")
    print(f"body_os_garmin_summary.json -> {summary_out}")
    if args.today_out:
        print(f"body_os_today_energy.json -> {args.today_out}")
    if args.runtime_energy_out:
        print(f"_energy_status.json -> {args.runtime_energy_out}")
    print(f"energy_daily: {len(dataset['energy_daily'])}")
    print(f"training_logs: {len(dataset['training_logs'])}")
    print(f"body_metrics: {len(dataset['body_metrics'])}")
    print(f"daily_wellness: {len(dataset['daily_wellness'])}")
    print(f"summary: {dataset['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
