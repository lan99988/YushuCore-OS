"""Garmin 7 天数据同步与 Body OS 映射。

Phase 1 目标：
- Garmin 只作为传感器层。
- 原始精简数据写入 raw_garmin_7d.json。
- 业务映射结果写入 body_os_mapped_7d.json。

导入本模块不依赖 garminconnect；只有执行真实拉取时才懒加载外部库。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


def _to_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if "T" in text:
        text = text.split("T", 1)[0]
    if " " in text:
        text = text.split(" ", 1)[0]
    return text[:10]


def _latest(items: list[dict[str, Any]], date_keys: tuple[str, ...]) -> dict[str, Any]:
    dated = []
    for item in items or []:
        date = None
        for key in date_keys:
            date = _to_date(item.get(key))
            if date:
                break
        if date:
            dated.append((date, item))
    if not dated:
        return {}
    return sorted(dated, key=lambda pair: pair[0])[-1][1]


def _normalize_sleep(item: dict[str, Any]) -> dict[str, Any]:
    daily = item.get("dailySleepDTO")
    if isinstance(daily, dict):
        merged = dict(item)
        merged.update(daily)
        return merged
    return item


def _sleep_score(sleep: dict[str, Any]) -> Any:
    score = sleep.get("sleepScore") or sleep.get("overallSleepScore")
    if score is not None:
        return score
    scores = sleep.get("sleepScores")
    if isinstance(scores, dict):
        overall = scores.get("overall")
        if isinstance(overall, dict):
            return overall.get("value")
    return None


def _filter_activities_by_date(
    activities: list[dict[str, Any]], start: _dt.date, end: _dt.date
) -> list[dict[str, Any]]:
    filtered = []
    for activity in activities or []:
        date_text = _to_date(activity.get("startTimeLocal") or activity.get("startTimeGMT"))
        if not date_text:
            continue
        try:
            activity_date = _dt.date.fromisoformat(date_text)
        except ValueError:
            continue
        if start <= activity_date <= end:
            filtered.append(activity)
    return filtered


def _seconds_to_hours(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value) / 3600, 2)


def _seconds_to_minutes(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value) / 60, 1)


def _meters_to_km(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value) / 1000, 2)


def _activity_type(activity: dict[str, Any]) -> str:
    raw_type = activity.get("activityType") or activity.get("activity_type") or {}
    if isinstance(raw_type, dict):
        key = raw_type.get("typeKey") or raw_type.get("type_key") or raw_type.get("name")
    else:
        key = str(raw_type)
    key = (key or "").lower()

    if any(token in key for token in ("run", "running", "trail_running", "treadmill")):
        return "running"
    if any(token in key for token in ("strength", "training", "cardio", "hiit")):
        return "strength"
    if any(token in key for token in ("yoga", "pilates", "mobility", "stretch")):
        return "mobility"
    return "other"


def _readiness_score(energy: dict[str, Any]) -> int | None:
    parts: list[float] = []

    sleep_hours = energy.get("sleep_hours")
    if sleep_hours is not None:
        parts.append(min(100.0, float(sleep_hours) / 8.0 * 100.0))

    sleep_quality = energy.get("sleep_quality")
    if sleep_quality is not None:
        parts.append(float(sleep_quality))

    stress = energy.get("stress_level")
    if stress is not None:
        parts.append(max(0.0, 100.0 - float(stress)))

    battery = energy.get("body_battery")
    if battery is not None:
        parts.append(float(battery))

    if not parts:
        return None
    return int(round(sum(parts) / len(parts)))


def map_to_body_os(raw: dict[str, Any]) -> dict[str, Any]:
    """把 Garmin 精简快照映射为 Body OS Phase 1 字段。"""
    sleep = _latest([_normalize_sleep(item) for item in raw.get("sleep", [])], ("calendarDate", "date"))
    heart_rate = _latest(raw.get("heart_rate", []), ("calendarDate", "date"))
    stress = _latest(raw.get("stress", []), ("calendarDate", "date"))
    body_battery = _latest(raw.get("body_battery", []), ("calendarDate", "date"))

    energy = {
        "date": _to_date(
            sleep.get("calendarDate")
            or heart_rate.get("calendarDate")
            or stress.get("calendarDate")
            or body_battery.get("calendarDate")
        ),
        "sleep_hours": _seconds_to_hours(
            sleep.get("sleepTimeSeconds")
            or sleep.get("duration")
            or sleep.get("sleep_seconds")
        ),
        "sleep_quality": _sleep_score(sleep),
        "stress_level": stress.get("avgStressLevel") or stress.get("averageStressLevel"),
        "resting_hr": heart_rate.get("restingHeartRate") or heart_rate.get("resting_hr"),
        "hrv_ms": heart_rate.get("lastNightAvg") or heart_rate.get("hrv_ms"),
        "body_battery": body_battery.get("charged") or body_battery.get("bodyBattery") or body_battery.get("value"),
        "source": "garmin",
    }
    energy["readiness_score"] = _readiness_score(energy)

    training_logs = []
    for activity in raw.get("activities", []) or []:
        training_logs.append(
            {
                "date": _to_date(activity.get("startTimeLocal") or activity.get("startTimeGMT")),
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

    dates = [
        date
        for date in [
            energy.get("date"),
            *[item.get("date") for item in training_logs],
        ]
        if date
    ]

    mapped = {
        "date_range": {
            "start": min(dates) if dates else None,
            "end": max(dates) if dates else None,
        },
        "energy": energy,
        "training_logs": training_logs,
    }
    mapped["today_decision"] = decide_today_focus(mapped)
    return mapped


def decide_today_focus(mapped: dict[str, Any]) -> dict[str, str]:
    """给 BodyController 的 Phase 1 简化建议。"""
    energy = mapped.get("energy", {})
    readiness = energy.get("readiness_score")
    sleep_hours = energy.get("sleep_hours")
    stress = energy.get("stress_level")
    battery = energy.get("body_battery")

    if readiness is not None and readiness < 45:
        return {
            "recommendation": "recovery",
            "reason": "睡眠、压力或身体可用能量显示恢复不足，优先恢复或轻活动。",
        }
    if sleep_hours is not None and sleep_hours < 6:
        return {
            "recommendation": "deload",
            "reason": "睡眠不足 6 小时，降低力量训练容量与强度。",
        }
    if stress is not None and stress >= 70:
        return {
            "recommendation": "zone2",
            "reason": "压力偏高，适合低强度 Zone2 或散步。",
        }
    if battery is not None and battery >= 65:
        return {
            "recommendation": "strength",
            "reason": "身体可用能量充足，适合执行计划内力量训练。",
        }
    return {
        "recommendation": "zone2",
        "reason": "恢复状态中等，优先稳定心肺底座或轻量力量训练。",
    }


class GarminCnGcApiClient:
    """Garmin CN Web gc-api client backed by the logged-in Chrome profile."""

    def __init__(self, profile_dir: str | None = None) -> None:
        self.profile_dir = Path(
            profile_dir
            or os.environ.get("GARMIN_CHROME_PROFILE")
            or r"C:\Users\26326\.garminconnect\chrome-login-profile"
        )
        self.chrome_path = os.environ.get(
            "GARMIN_CHROME_PATH",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        self._playwright = None
        self._context = None
        self._page = None
        self._display_name: str | None = None
        self._csrf_token: str | None = None

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._context = None
        self._playwright = None
        self._page = None

    def _get_page(self):
        if self._page is not None:
            return self._page

        from playwright.sync_api import sync_playwright

        pw_kwargs: dict = {
            "headless": True,
            "viewport": {"width": 1280, "height": 900},
            "args": [
                "--disable-background-networking",
                "--disable-sync",
                "--no-first-run",
            ],
        }
        # Auto-detect proxy from environment
        proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy_url:
            pw_kwargs["proxy"] = {"server": proxy_url}
            print(f"  [Playwright] 使用代理: {proxy_url}")

        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            executable_path=self.chrome_path,
            **pw_kwargs,
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

        def capture_csrf(request) -> None:
            token = request.headers.get("connect-csrf-token")
            if token:
                self._csrf_token = token

        self._page.on("request", capture_csrf)
        self._page.goto(
            "https://connect.garmin.cn/app/home",
            wait_until="domcontentloaded",
            timeout=45000,
        )
        self._page.wait_for_timeout(5000)
        return self._page

    def gc_api(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = f"?{urlencode(params)}" if params else ""
        url = f"/gc-api/{path.lstrip('/')}{query}"
        result = self._get_page().evaluate(
            """async ({ url, csrf }) => {
                const headers = {
                    "Accept": "application/json, text/plain, */*",
                    "NK": "NT"
                };
                if (csrf) {
                    headers["connect-csrf-token"] = csrf;
                }
                const response = await fetch(url, {
                    credentials: "include",
                    headers
                });
                const text = await response.text();
                let body = null;
                if (text) {
                    try {
                        body = JSON.parse(text);
                    } catch {
                        body = text;
                    }
                }
                return { status: response.status, body };
            }""",
            {"url": url, "csrf": self._csrf_token},
        )
        if result["status"] >= 400:
            raise RuntimeError(f"Garmin CN gc-api error {result['status']}: {path}")
        return result["body"] or {}

    def display_name(self) -> str:
        if self._display_name:
            return self._display_name

        profile = self.gc_api("/userprofile-service/userprofile/userProfileBase")
        display_name = (
            profile.get("displayName")
            or profile.get("userName")
            or profile.get("profileId")
            or profile.get("userProfileId")
        )
        if not display_name:
            raise RuntimeError("Garmin CN gc-api did not return a display/profile id")
        self._display_name = str(display_name)
        return self._display_name

    def fetch_7d(self, email: str | None = None) -> dict[str, Any]:
        try:
            today = _dt.date.today()
            start = today - _dt.timedelta(days=6)
            days = [(start + _dt.timedelta(days=i)).isoformat() for i in range(7)]
            display_name = self.display_name()
            activities = self.gc_api(
                "/activitylist-service/activities/search/activities",
                {"start": "0", "limit": "20"},
            )
            if isinstance(activities, list):
                activities = _filter_activities_by_date(activities, start, today)
            return {
                "meta": {
                    "account": email,
                    "fetched_at": _dt.datetime.now().isoformat(timespec="seconds"),
                    "start": start.isoformat(),
                    "end": today.isoformat(),
                    "source": "garmin_cn_gc_api",
                },
                "sleep": [
                    self.gc_api(
                        f"/wellness-service/wellness/dailySleepData/{display_name}",
                        {"date": day, "nonSleepBufferMinutes": 60},
                    )
                    for day in days
                ],
                "activities": activities,
                "heart_rate": [
                    self.gc_api(
                        f"/wellness-service/wellness/dailyHeartRate/{display_name}",
                        {"date": day},
                    )
                    for day in days
                ],
                "stress": [
                    self.gc_api(f"/wellness-service/wellness/dailyStress/{day}")
                    for day in days
                ],
                "body_battery": self.gc_api(
                    "/wellness-service/wellness/bodyBattery/reports/daily",
                    {"startDate": start.isoformat(), "endDate": today.isoformat()},
                ),
            }
        finally:
            self.close()


def fetch_garmin_7d(email: str | None = None) -> dict[str, Any]:
    """真实拉取 Garmin 近 7 天精简数据。

    依赖已完成交互登录并在 GARMIN_TOKEN_DIR 中保存 token。
    """
    from garminconnect import Garmin

    today = _dt.date.today()
    start = today - _dt.timedelta(days=6)
    is_cn = os.environ.get("GARMIN_IS_CN", "").lower() == "true"
    tokenstore = os.environ.get("GARMIN_TOKEN_DIR")
    client = Garmin(is_cn=is_cn)
    try:
        client.login(tokenstore=tokenstore)
    except Exception:
        if not is_cn:
            raise
        profile_dir = os.environ.get("GARMIN_CHROME_PROFILE")
        return GarminCnGcApiClient(profile_dir=profile_dir).fetch_7d(email)

    days = [(start + _dt.timedelta(days=i)).isoformat() for i in range(7)]
    activities = client.get_activities(0, 20)
    if isinstance(activities, list):
        activities = _filter_activities_by_date(activities, start, today)
    return {
        "meta": {
            "account": email,
            "fetched_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "start": start.isoformat(),
            "end": today.isoformat(),
        },
        "sleep": [client.get_sleep_data(day) for day in days],
        "activities": activities,
        "heart_rate": [client.get_heart_rates(day) for day in days],
        "stress": [client.get_stress_data(day) for day in days],
        "body_battery": [client.get_body_battery(day) for day in days],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Garmin 7d data into Body OS JSON snapshots.")
    parser.add_argument("--email", default=os.environ.get("GARMIN_EMAIL"))
    parser.add_argument("--raw-input", help="Use an existing raw Garmin JSON instead of calling Garmin.")
    parser.add_argument("--out-dir", default=str(Path.cwd()))
    args = parser.parse_args()

    if args.raw_input:
        raw = json.loads(Path(args.raw_input).read_text(encoding="utf-8"))
    else:
        raw = fetch_garmin_7d(args.email)

    mapped = map_to_body_os(raw)
    out_dir = Path(args.out_dir)
    _write_json(out_dir / "raw_garmin_7d.json", raw)
    _write_json(out_dir / "body_os_mapped_7d.json", mapped)

    print(f"raw_garmin_7d.json -> {out_dir / 'raw_garmin_7d.json'}")
    print(f"body_os_mapped_7d.json -> {out_dir / 'body_os_mapped_7d.json'}")
    print(f"today_decision -> {mapped['today_decision']['recommendation']}: {mapped['today_decision']['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
