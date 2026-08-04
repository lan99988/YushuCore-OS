"""Discover Garmin CN Web gc-api endpoints from the logged-in Connect app.

The catalog intentionally stores request/response metadata only. It must not
store cookies, tokens, full JSON response bodies, or other session secrets.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


CONNECT_HOST = "connect.garmin.cn"
APP_PREFIX = f"https://{CONNECT_HOST}/app"
DEFAULT_PROFILE = r"C:\Users\26326\.garminconnect\chrome-login-profile"
DEFAULT_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

SEED_ROUTES = [
    {"label": "主页", "url": f"{APP_PREFIX}/home"},
    {"label": "活动", "url": f"{APP_PREFIX}/activities"},
    {"label": "健康统计", "url": f"{APP_PREFIX}/health"},
    {"label": "睡眠", "url": f"{APP_PREFIX}/sleep"},
    {"label": "身体电量", "url": f"{APP_PREFIX}/bodybattery"},
    {"label": "压力", "url": f"{APP_PREFIX}/stress"},
    {"label": "心率", "url": f"{APP_PREFIX}/heartrate"},
    {"label": "报告", "url": f"{APP_PREFIX}/reports"},
]


def normalize_api_call(
    url: str,
    *,
    status: int,
    method: str = "GET",
    body: Any = None,
    pages: list[str] | None = None,
) -> dict[str, Any]:
    parsed = urlparse(url)
    path = parsed.path
    if path.startswith("/gc-api/"):
        path = path.removeprefix("/gc-api")
    query_keys = sorted(parse_qs(parsed.query, keep_blank_values=True).keys())
    body_type = type(body).__name__ if body is not None else None
    top_level_keys: list[str] = []
    if isinstance(body, dict):
        top_level_keys = sorted(str(key) for key in body.keys())
    elif isinstance(body, list) and body and isinstance(body[0], dict):
        top_level_keys = sorted(str(key) for key in body[0].keys())

    key = f"{method.upper()} {path}?{','.join(query_keys)}"
    return {
        "key": key,
        "method": method.upper(),
        "path": path,
        "query_keys": query_keys,
        "status": int(status),
        "statuses": [int(status)],
        "body_type": body_type,
        "top_level_keys": top_level_keys,
        "pages": pages or [],
        "count": 1,
    }


def merge_api_call(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    page_names = [*existing.get("pages", []), *incoming.get("pages", [])]
    merged["pages"] = sorted(dict.fromkeys(page_names))
    statuses = [*existing.get("statuses", []), incoming.get("status")]
    merged["statuses"] = sorted({int(status) for status in statuses if status is not None})
    merged["count"] = int(existing.get("count", 0)) + 1
    return merged


def _fallback_label(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path or url


def select_routes(
    links: list[dict[str, str]], *, max_routes: int
) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in links:
        href = (link.get("href") or "").split("#", 1)[0]
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc != CONNECT_HOST or not parsed.path.startswith("/app/"):
            continue
        if href in seen:
            continue
        seen.add(href)
        label = (link.get("label") or "").strip() or _fallback_label(href)
        routes.append({"label": label, "url": href})
        if len(routes) >= max_routes:
            break
    return routes


def _extract_app_links(page) -> list[dict[str, str]]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href]')).map((a) => ({
            label: (a.innerText || a.getAttribute('aria-label') || a.title || '').trim(),
            href: a.href
        }))"""
    )


def _safe_json_body(response) -> Any:
    try:
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type.lower():
            return None
        return response.json()
    except Exception:
        return None


def discover_catalog(max_routes: int = 35) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    profile_dir = os.environ.get("GARMIN_CHROME_PROFILE", DEFAULT_PROFILE)
    chrome_path = os.environ.get("GARMIN_CHROME_PATH", DEFAULT_CHROME)
    api_calls: dict[str, dict[str, Any]] = {}
    visited_pages: list[dict[str, Any]] = []
    current_page_label = "启动"

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile_dir,
            executable_path=chrome_path,
            headless=True,
            viewport={"width": 1360, "height": 960},
            args=[
                "--disable-background-networking",
                "--disable-sync",
                "--no-first-run",
            ],
        )
        page = context.new_page()

        def on_response(response) -> None:
            if "/gc-api/" not in response.url:
                return
            request = response.request
            call = normalize_api_call(
                response.url,
                status=response.status,
                method=request.method,
                body=_safe_json_body(response),
                pages=[current_page_label],
            )
            existing = api_calls.get(call["key"])
            api_calls[call["key"]] = merge_api_call(existing, call) if existing else call

        page.on("response", on_response)
        queue = list(SEED_ROUTES)
        seen_urls: set[str] = set()

        while queue and len(visited_pages) < max_routes:
            route = queue.pop(0)
            url = route["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            current_page_label = route["label"]
            try:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    page.wait_for_timeout(3000)
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                title = page.title()
                links = _extract_app_links(page)
                discovered = select_routes(links, max_routes=max_routes)
                for item in discovered:
                    if item["url"] not in seen_urls and item["url"] not in {
                        queued["url"] for queued in queue
                    }:
                        queue.append(item)
                visited_pages.append(
                    {
                        "label": route["label"],
                        "url": url,
                        "title": title,
                        "discovered_route_count": len(discovered),
                    }
                )
            except Exception as exc:
                visited_pages.append(
                    {
                        "label": route["label"],
                        "url": url,
                        "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                    }
                )

        context.close()

    return {
        "meta": {
            "source": "garmin_cn_web_discovery",
            "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "max_routes": max_routes,
        },
        "pages": visited_pages,
        "api_calls": sorted(api_calls.values(), key=lambda item: item["key"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover Garmin CN Web gc-api calls.")
    parser.add_argument("--max-routes", type=int, default=35)
    parser.add_argument("--out", default="garmin_cn_api_catalog.json")
    args = parser.parse_args()

    catalog = discover_catalog(max_routes=args.max_routes)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"catalog -> {out}")
    print(f"pages -> {len(catalog['pages'])}")
    print(f"api_calls -> {len(catalog['api_calls'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
