import os
import sys
import unittest


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(WORKSPACE, "08_工具脚本（Tools）", "身体管理")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


class GarminCnDiscoverTest(unittest.TestCase):
    def test_normalize_api_call_keeps_path_and_query_keys_without_values(self):
        from garmin_cn_discover import normalize_api_call

        call = normalize_api_call(
            "https://connect.garmin.cn/gc-api/usersummary-service/usersummary/daily/user123?calendarDate=2026-07-29&_ignore=1",
            status=200,
            method="GET",
            body={"calendarDate": "2026-07-29", "totalSteps": 1234},
        )

        self.assertEqual(
            call["path"], "/usersummary-service/usersummary/daily/user123"
        )
        self.assertEqual(call["query_keys"], ["_ignore", "calendarDate"])
        self.assertEqual(call["status"], 200)
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["body_type"], "dict")
        self.assertEqual(call["top_level_keys"], ["calendarDate", "totalSteps"])

    def test_merge_api_call_counts_repeated_endpoint_without_duplicate_pages(self):
        from garmin_cn_discover import merge_api_call

        existing = {
            "key": "GET /x?a",
            "pages": ["主页"],
            "count": 1,
            "statuses": [200],
        }
        incoming = {"pages": ["主页", "睡眠"], "status": 404}

        merged = merge_api_call(existing, incoming)

        self.assertEqual(merged["pages"], ["主页", "睡眠"])
        self.assertEqual(merged["count"], 2)
        self.assertEqual(merged["statuses"], [200, 404])

    def test_select_routes_keeps_garmin_app_routes_and_nested_items(self):
        from garmin_cn_discover import select_routes

        links = [
            {"label": "健康统计", "href": "https://connect.garmin.cn/app/health"},
            {"label": "睡眠", "href": "https://connect.garmin.cn/app/sleep"},
            {"label": "外部", "href": "https://example.com"},
            {"label": "", "href": "https://connect.garmin.cn/app/stress"},
        ]

        routes = select_routes(links, max_routes=10)

        self.assertEqual(
            routes,
            [
                {"label": "健康统计", "url": "https://connect.garmin.cn/app/health"},
                {"label": "睡眠", "url": "https://connect.garmin.cn/app/sleep"},
                {"label": "/app/stress", "url": "https://connect.garmin.cn/app/stress"},
            ],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
