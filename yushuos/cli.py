"""Stable, single-JSON-output command line interface."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import default_root
from .models import Result
from .runtime import CoreRuntime


def _read_json(path: str) -> Any:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("JSON 不能含 NaN 或 Infinity")))


def run(args: argparse.Namespace) -> Any:
    if args.command in {"deploy", "activate", "verify", "rollback", "install-host", "uninstall-host", "install-plugin", "lock-plugin", "sync-app-plugin"}:
        from .deployment import activate_release, deploy, install_host, install_plugin, lock_plugin, rollback, sync_app_plugin, uninstall_host, verify_release
        if args.command == "deploy":
            return deploy(args.source, args.config_root, args.version, activate=not args.preview)
        if args.command == "activate":
            return activate_release(args.config_root, args.version)
        if args.command == "install-host":
            return install_host(args.config_root, args.host_config_root, host=args.host)
        if args.command == "uninstall-host":
            return uninstall_host(args.config_root, args.host_config_root, host=args.host)
        if args.command == "install-plugin":
            return install_plugin(args.path, args.config_root)
        if args.command == "verify":
            return verify_release(args.config_root, args.version)
        if args.command == "lock-plugin":
            return lock_plugin(args.path)
        if args.command == "sync-app-plugin":
            return sync_app_plugin(args.config_root, args.app_root, app=args.app)
        return rollback(args.config_root)
    runtime = CoreRuntime(args.config_root, project_file=args.project_file)
    if args.command == "doctor":
        return runtime.doctor()
    if args.command == "catalog":
        return runtime.registry.catalog()
    if args.command == "parse":
        return runtime.parse(args.text)
    if args.command == "plan":
        return runtime.plan(_read_json(args.file))
    if args.command == "invoke":
        value = _read_json(args.file)
        return runtime.invoke(value, mode=args.mode, host_mode=args.host_mode).to_dict()
    if args.command == "workflow":
        value = _read_json(args.file)
        return runtime.plan(value) if args.mode == "preview" or args.host_mode != "execute" else runtime.execute_plan(value, host_mode=args.host_mode)
    if args.command == "status":
        if not runtime.state:
            return {"status": "unavailable", "message": "尚未绑定共享操作台账"}
        if args.plan_id:
            workflow = runtime.state.workflow(args.plan_id)
            return {"status": "unavailable", "plan_id": args.plan_id} if workflow is None else workflow
        receipt = runtime.state.receipt(args.request_id)
        return {"status": "unavailable", "request_id": args.request_id} if receipt is None else receipt
    if args.command == "resume":
        value = _read_json(args.file)
        if isinstance(value, dict) and "steps" in value:
            return runtime.resume_plan(value, host_mode=args.host_mode)
        return runtime.resume(value, host_mode=args.host_mode).to_dict()
    raise ValueError("不支持的命令")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yushuos", description="YushuOS 轻量本体 V0.2")
    parser.add_argument("--config-root", default=str(default_root()))
    parser.add_argument("--project-file", default=None)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("catalog")
    parse = commands.add_parser("parse")
    parse.add_argument("--text", required=True)
    for name in ("plan", "invoke", "workflow", "resume"):
        command = commands.add_parser(name)
        command.add_argument("--file", default="-")
        if name in {"invoke", "workflow"}:
            command.add_argument("--mode", choices=("preview", "execute"), default="preview")
            command.add_argument("--host-mode", choices=("readonly", "ask", "plan", "quick", "execute"), default="readonly")
        if name == "resume":
            command.add_argument("--host-mode", choices=("readonly", "ask", "plan", "quick", "execute"), default="execute")
    status = commands.add_parser("status")
    target = status.add_mutually_exclusive_group(required=True)
    target.add_argument("--request-id")
    target.add_argument("--plan-id")
    deploy_parser = commands.add_parser("deploy")
    deploy_parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1]))
    deploy_parser.add_argument("--version", required=True)
    deploy_parser.add_argument("--preview", action="store_true", help="只部署并校验候选版本，不切换活动指针")
    activate = commands.add_parser("activate")
    activate.add_argument("--version", required=True)
    install = commands.add_parser("install-host")
    install.add_argument("--host", choices=("codex", "workbuddy"), required=True)
    install.add_argument("--host-config-root", required=True)
    uninstall = commands.add_parser("uninstall-host")
    uninstall.add_argument("--host", choices=("codex", "workbuddy"), required=True)
    uninstall.add_argument("--host-config-root", required=True)
    lock = commands.add_parser("lock-plugin")
    lock.add_argument("--path", required=True)
    install_plugin_parser = commands.add_parser("install-plugin")
    install_plugin_parser.add_argument("--path", required=True)
    sync = commands.add_parser("sync-app-plugin")
    sync.add_argument("--app", choices=("ima", "feishu"), required=True)
    sync.add_argument("--app-root", required=True, help="独立 App 安装根目录，例如 .agent-apps")
    verify = commands.add_parser("verify")
    verify.add_argument("--version", default=None)
    commands.add_parser("rollback")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = _parser()
    try:
        result = run(parser.parse_args(argv))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        # Never echo parser/remote exception text: it may contain private inputs.
        safe = str(exc) if isinstance(exc, ValueError) and len(str(exc)) <= 180 else f"操作未完成：{type(exc).__name__}"
        print(json.dumps({"status": "failed", "message": safe}, ensure_ascii=False))
        return 1
