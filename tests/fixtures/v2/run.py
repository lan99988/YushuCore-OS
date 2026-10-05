"""Reference json-stdio-v1 plugin entry point."""

import json
import sys

from yushuos_sdk import Request, Result


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if payload.get("protocol") != "json-stdio-v1" or payload.get("action") != "invoke":
            raise ValueError("unsupported protocol")
        request = Request(**payload["request"])
        result = Result("succeeded", request.request_id, "示例插件已收到请求", data={"received": request.fields["message"]})
        print(json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False))
        return 0
    except Exception:
        print(json.dumps({"status": "failed", "request_id": "invalid", "message": "示例插件无法解析请求"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
