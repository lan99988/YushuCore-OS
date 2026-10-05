"""json-stdio adapter for an independently installed app_plugins release."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


_STATUSES = {"preview", "succeeded", "partial", "verification_pending", "unknown", "failed", "unavailable", "needs_clarification"}


def _failure(request_id: str, status: str = "unavailable", message: str = "App 插件绑定或发布校验未通过") -> dict:
    return {"status": status, "request_id": request_id, "message": message, "resource": {}, "data": None, "error": None}


def _submitting_write(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    return (payload.get("capability_effect") in {"internal_write", "external_write"}
            and payload.get("mode") == "execute" and payload.get("host_mode") == "execute")


def _safe_absolute(value: object, *, must_exist: str | None = None) -> Path:
    if not isinstance(value, str):
        raise ValueError("path invalid")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("path must be absolute")
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("linked paths are forbidden")
    if must_exist == "file" and not path.is_file() or must_exist == "dir" and not path.is_dir():
        raise ValueError("bound path is missing")
    return path


def _verified_binding(payload: dict) -> tuple[str, Path, Path, Path, Path, str, Path]:
    app_id = payload.get("plugin_id", "")
    if not isinstance(app_id, str) or not app_id.startswith("app-"):
        raise ValueError("plugin id invalid")
    app = app_id.removeprefix("app-")
    binding = payload.get("app_binding")
    if not isinstance(binding, dict):
        raise ValueError("app binding missing")
    pointer = _safe_absolute(binding.get("active_pointer"), must_exist="file")
    pointer_data = json.loads(pointer.read_text(encoding="utf-8-sig"))
    if not isinstance(pointer_data, dict) or pointer_data.get("app") != app:
        raise ValueError("app binding mismatch")
    version = pointer_data.get("version")
    if version != payload.get("plugin_version"):
        raise ValueError("app release version mismatch")
    release = _safe_absolute(pointer_data.get("release"), must_exist="dir")
    config_file = _safe_absolute(pointer_data.get("config_file"), must_exist="file")
    ledger_path = _safe_absolute(pointer_data.get("ledger_path"),must_exist='file')
    python = _safe_absolute(pointer_data.get("python_executable"), must_exist="file")
    manifest_path = _safe_absolute(str(release / "manifest.json"), must_exist="file")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if (not isinstance(manifest, dict) or manifest.get("app") != app or manifest.get("version") != version
            or not isinstance(manifest.get("files"), dict)):
        raise ValueError("app release manifest invalid")
    expected = manifest["files"]
    actual: dict[str, str] = {}
    for item in release.rglob("*"):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("app release contains a link")
        if not item.is_file() or item == manifest_path or "__pycache__" in item.parts or item.suffix in {".pyc", ".pyo"}:
            continue
        actual[item.relative_to(release).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("app release hash mismatch")
    entry = _safe_absolute(str(release / "app_plugins" / "__main__.py"), must_exist="file")
    request = payload.get("request")
    if not isinstance(request, dict) or not isinstance(request.get("request_id"), str):
        raise ValueError("request invalid")
    if _submitting_write(payload):
        core_ledger=_safe_absolute(payload.get('state_ledger_path'),must_exist='file')
        if core_ledger.resolve()!=ledger_path.resolve():
            raise ValueError('app and Core operation ledgers differ')
    return app, release, entry, config_file, ledger_path, str(version), python


def main() -> int:
    payload = {}
    dispatched = False
    try:
        payload = json.load(sys.stdin, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")))
        if not isinstance(payload, dict) or payload.get("protocol") not in {"json-stdio-v1","json-stdio-v2"} or payload.get("action") != "invoke":
            raise ValueError("protocol invalid")
        app, release, entry, config_file, ledger_path, version, python = _verified_binding(payload)
        request = payload["request"]
        project_ref = request.get("project_ref", "")
        if not isinstance(project_ref, str):
            raise ValueError("project scope invalid")
        args = [str(python), str(entry), "--app", app, "--config-file", str(config_file),
                "--ledger-path", str(ledger_path), "--project-ref", project_ref, "--version", version,
                "invoke", "--file", "-", "--mode", payload.get("mode", "preview"),
                "--host-mode", payload.get("host_mode", "readonly")]
        env_names = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA")
        env = {name: os.environ[name] for name in env_names if name in os.environ}
        env["PYTHONUTF8"] = "1"
        env["YUSHUOS_HOME"] = payload.get("config_root", "")
        env["PYTHONPATH"] = str(release)
        if payload['protocol']=='json-stdio-v2':
            from yushuos_sdk import PluginContext
            context=PluginContext.from_envelope(payload)
            # The generic App CLI reads the same request JSON as legacy Apps;
            # the runtime-bound context is provided separately for SDK receipts.
            env['YUSHUOS_PLUGIN_CONTEXT']=json.dumps(context.to_dict(),ensure_ascii=False,allow_nan=False)
            import yushuos_sdk
            env['PYTHONPATH']=os.pathsep.join((str(release),str(Path(yushuos_sdk.__file__).resolve().parents[1])))
        dispatched = True
        process = subprocess.run(args, input=json.dumps(request, ensure_ascii=False, allow_nan=False),
                                  capture_output=True, text=True, encoding="utf-8", timeout=80,
                                  cwd=str(release), env=env)
        result = json.loads(process.stdout, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")))
        if (not isinstance(result, dict) or result.get("request_id") != request["request_id"]
                or result.get("status") not in _STATUSES or set(result) - {"status", "request_id", "message", "resource", "data", "error"}):
            raise ValueError("app result invalid")
        if process.returncode and result.get("status") in {"succeeded", "preview"}:
            raise ValueError("app result exit status invalid")
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except subprocess.TimeoutExpired:
        request = payload.get("request", {}) if isinstance(payload, dict) else {}
        result = _failure(request.get("request_id", "invalid"), "unknown" if _submitting_write(payload) else "unavailable",
                          "App 调用超时，写入结果需按原请求 ID 核对")
    except OSError:
        request = payload.get("request", {}) if isinstance(payload, dict) else {}
        status = "unknown" if dispatched and _submitting_write(payload) else "unavailable"
        result = _failure(request.get("request_id", "invalid"), status)
    except Exception:
        request = payload.get("request", {}) if isinstance(payload, dict) else {}
        status = "unknown" if dispatched and _submitting_write(payload) else "unavailable"
        result = _failure(request.get("request_id", "invalid"), status)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
