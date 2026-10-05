"""Local-only v3 demonstration plugin for automation and event delivery."""

import json
import os
from pathlib import Path
import sys
import uuid

from yushuos_sdk import Request, Result, StateStore
from yushuos_sdk.context import PluginContext
from yushuos_sdk.canonical import loads


def _write_count(path: Path, value: int) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps({"count": value}, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _count(data_path: Path) -> int:
    counter = data_path / "demo-counter.json"
    if not counter.exists():
        return 0
    value = loads(counter.read_bytes())
    if not isinstance(value, dict) or type(value.get("count")) is not int or value["count"] < 0:
        raise ValueError("counter state is invalid")
    return value["count"]


def _json_result(result: Result) -> None:
    print(json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False))


def main() -> int:
    request_id = "invalid"
    try:
        envelope = loads(sys.stdin.buffer.read())
        if not isinstance(envelope, dict) or envelope.get("protocol") != "json-stdio-v2" or envelope.get("action") != "invoke":
            raise ValueError("invalid invocation envelope")
        context = PluginContext.from_envelope(envelope)
        request = Request(**envelope["request"])
        request_id = request.request_id
        data_path = Path(context.data_path)
        data_path.mkdir(parents=True, exist_ok=True)

        if envelope.get("capability") == "demo.counter.create":
            state = StateStore(context.state_ledger_path)
            if not state.claim(request):
                receipt = state.receipt(request.request_id)
                if receipt and receipt.get("receipt"):
                    _json_result(Result(**receipt["receipt"]))
                else:
                    _json_result(Result("unknown", request.request_id, "Existing request requires readback."))
                return 0
            current = _count(data_path)
            updated = current + 1
            _write_count(data_path / "demo-counter.json", updated)
            result = Result("succeeded", request.request_id, "Demo counter incremented.",
                            resource={"id": f"demo-{updated}"}, data={"count": updated})
            state.record_with_events(result, context, [{
                "type": "demo.created",
                "resource_refs": {"id": f"demo-{updated}"},
            }])
            _json_result(result)
            return 0

        if envelope.get("capability") in {"demo.counter.inspect", "demo.counter.review"}:
            _json_result(Result("succeeded", request.request_id,
                                "Demo counter inspected.", data={"count": _count(data_path)}))
            return 0

        _json_result(Result("unavailable", request.request_id, "Unknown demo capability."))
        return 0
    except Exception:
        _json_result(Result("unknown", request_id, "Demo invocation needs local review."))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
