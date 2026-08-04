# Garmin CN 365d Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Garmin China Web API discovery pipeline that explores the main sidebar and nested pages, records reusable `gc-api` endpoints, then supports a near-one-year data sync.

**Architecture:** Reuse the already-authenticated Chrome profile and Garmin Web session because CN `gc-api` calls require browser cookies plus `connect-csrf-token`. First discover and catalog endpoints from page navigation, then use stable endpoints directly for long-range sync. Do not store tokens, cookies, or response bodies in the catalog.

**Tech Stack:** Python 3.13, Playwright sync API, Garmin CN `connect.garmin.cn/gc-api`, existing Body OS scripts under `08_工具脚本（Tools）/身体管理`.

---

### Task 1: API Catalog Helpers

**Files:**
- Create: `08_工具脚本（Tools）/身体管理/garmin_cn_discover.py`
- Test: `tests/test_garmin_cn_discover.py`

- [ ] **Step 1: Write failing tests**

```python
from garmin_cn_discover import normalize_api_call, merge_api_call


def test_normalize_api_call_keeps_path_and_query_keys_without_values():
    call = normalize_api_call(
        "https://connect.garmin.cn/gc-api/usersummary-service/usersummary/daily/user123?calendarDate=2026-07-29&_ignore=1",
        status=200,
        method="GET",
        body={"calendarDate": "2026-07-29", "totalSteps": 1234},
    )
    assert call["path"] == "/usersummary-service/usersummary/daily/user123"
    assert call["query_keys"] == ["_ignore", "calendarDate"]
    assert call["status"] == 200
    assert call["method"] == "GET"
    assert call["body_type"] == "dict"
    assert call["top_level_keys"] == ["calendarDate", "totalSteps"]


def test_merge_api_call_counts_repeated_endpoint_without_duplicate_pages():
    existing = {
        "key": "GET /x?a",
        "pages": ["主页"],
        "count": 1,
        "statuses": [200],
    }
    incoming = {"pages": ["主页", "睡眠"], "status": 404}
    merged = merge_api_call(existing, incoming)
    assert merged["pages"] == ["主页", "睡眠"]
    assert merged["count"] == 2
    assert merged["statuses"] == [200, 404]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_garmin_cn_discover`

Expected: FAIL because `garmin_cn_discover` does not exist.

- [ ] **Step 3: Implement helper functions**

Add `normalize_api_call()` to remove host, retain path, sorted query keys, HTTP method, status, body type, and JSON top-level keys. Add `merge_api_call()` to deduplicate page labels and status codes while incrementing count.

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_garmin_cn_discover`

Expected: OK.

### Task 2: Sidebar And Nested Page Discovery

**Files:**
- Modify: `08_工具脚本（Tools）/身体管理/garmin_cn_discover.py`
- Test: `tests/test_garmin_cn_discover.py`

- [ ] **Step 1: Write failing tests for route selection**

```python
from garmin_cn_discover import select_routes


def test_select_routes_keeps_garmin_app_routes_and_nested_items():
    links = [
        {"label": "健康统计", "href": "https://connect.garmin.cn/app/health"},
        {"label": "睡眠", "href": "https://connect.garmin.cn/app/sleep"},
        {"label": "外部", "href": "https://example.com"},
    ]
    routes = select_routes(links, max_routes=10)
    assert routes == [
        {"label": "健康统计", "url": "https://connect.garmin.cn/app/health"},
        {"label": "睡眠", "url": "https://connect.garmin.cn/app/sleep"},
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_garmin_cn_discover`

Expected: FAIL because `select_routes` does not exist.

- [ ] **Step 3: Implement discovery runner**

Implement a Playwright runner that:
- Launches `C:\Users\26326\.garminconnect\chrome-login-profile`.
- Opens `https://connect.garmin.cn/app/home`.
- Captures `gc-api` request/response metadata.
- Extracts visible `/app/...` links from each page.
- Visits seed routes and discovered nested routes breadth-first with a route cap.
- Writes `garmin_cn_api_catalog.json`.

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_garmin_cn_discover tests.test_garmin_bodyos_sync tests.test_body_os_contract`

Expected: OK.

### Task 3: Generate Current Catalog

**Files:**
- Generate: `08_工具脚本（Tools）/身体管理/garmin_cn_api_catalog.json`

- [ ] **Step 1: Run discovery with a conservative cap**

Run:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:GARMIN_CHROME_PROFILE='C:\Users\26326\.garminconnect\chrome-login-profile'
& 'C:\Users\26326\.workbuddy\binaries\python\envs\default\Scripts\python.exe' 'D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\garmin_cn_discover.py' --max-routes 35 --out 'D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\garmin_cn_api_catalog.json'
```

Expected: Catalog file exists, contains page labels, routes, API calls, statuses, and top-level keys.

### Task 4: 365-Day Sync Follow-Up

**Files:**
- Create later: `08_工具脚本（Tools）/身体管理/garmin_sync_365d.py`
- Test later: `tests/test_garmin_sync_365d.py`

- [ ] **Step 1: Read the generated catalog**

Use only endpoints with stable date or pagination parameters.

- [ ] **Step 2: Implement long-range sync**

Fetch activities with pagination and fetch daily health dimensions by date range or day loop. Start with known stable dimensions: activities, daily summary, sleep, heart rate, stress, body battery.

- [ ] **Step 3: Verify on a shorter range before 365 days**

Run first with `--days 14`, then with `--days 365` after endpoint behavior is confirmed.

---

## Self-Review

- Spec coverage: Covers sidebar and nested route discovery, catalog generation, and 365-day sync follow-up.
- Placeholder scan: No `TBD` or open-ended implementation placeholders; the 365-day sync is intentionally a follow-up task after catalog evidence exists.
- Type consistency: Helper names and file paths are consistent across tasks.
