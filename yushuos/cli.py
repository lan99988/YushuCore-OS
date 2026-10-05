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


def _automation_command(args, runtime):
    from .automation import AutomationEngine
    from yushuos_sdk.canonical import loads
    engine = AutomationEngine(runtime)
    operation = args.operation
    if args.command == 'automation':
        if operation == 'add':
            raw = sys.stdin.read() if args.file == '-' else Path(args.file).read_bytes()
            return engine.add(loads(raw))
        if operation == 'list':
            return {'rules':[r for r in engine.store.list_rules() if r['project_ref']==runtime.config.get('project_ref','')]}
        if operation == 'show':
            return engine._rule(args.rule)
        if operation in {'enable','disable'}:
            engine._rule(args.rule)
            engine.store.set_enabled(args.rule,operation=='enable')
            return engine._rule(args.rule)
        if operation == 'preview':
            return engine.preview(args.rule)
        if operation == 'grant':
            return engine.grant(args.rule)
        if operation == 'revoke':
            engine._rule(args.rule)
            return {'rule_id':args.rule,'revoked':engine.store.revoke(args.rule)}
        if operation == 'run':
            return engine.run(args.rule,invocation_id=args.invocation_id,run_id=args.run_id,host=args.host_mode=='execute')
        if operation == 'tick':
            return engine.tick()
        if operation == 'worker':
            if args.max_ticks is not None and args.max_ticks<1:
                raise ValueError('max-ticks 必须为正整数')
            return engine.worker(max_ticks=args.max_ticks)
    if args.command == 'events':
        if operation == 'publish':
            raw = sys.stdin.read() if args.file == '-' else Path(args.file).read_bytes()
            return engine.publish(loads(raw))
        if operation == 'list':
            return {'events':[e for e in engine.store.list_events() if e['project_ref']==runtime.config.get('project_ref','')]}
        event = engine.store.show_event(args.event_id)
        if event is None or event['project_ref']!=runtime.config.get('project_ref',''):
            raise ValueError('事件在当前项目中不可用')
        return event
    if operation == 'resolve':
        return engine.resolve(args.request_id,args.outcome,reason_code=args.reason_code,evidence_ref=args.evidence_ref)
    if operation == 'list':
        runs = engine.store.list_runs(rule_id=args.rule,status=args.status)
        return {'runs':[r for r in runs if engine.store.get_rule(r['rule_id'])['project_ref']==runtime.config.get('project_ref','')]}
    value = engine.store.show_run(args.run_id)
    if value is None:
        raise ValueError('执行记录不存在')
    engine._rule(value['rule_id'])
    return value


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
    if args.command in {'automation','events','history'}:
        return _automation_command(args,runtime)
    if args.command == "doctor":
        return runtime.doctor()
    if args.command == "catalog":
        return runtime.registry.catalog(details=args.details)
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
        receipt = runtime.state.status_with_provenance(args.request_id)
        return {"status": "unavailable", "request_id": args.request_id} if receipt is None else receipt
    if args.command == "resume":
        value = _read_json(args.file)
        if isinstance(value, dict) and "steps" in value:
            return runtime.resume_plan(value, host_mode=args.host_mode)
        return runtime.resume(value, host_mode=args.host_mode).to_dict()
    raise ValueError("不支持的命令")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yushuos", description="YushuOS 本地插件执行运行时 V0.3")
    parser.add_argument("--config-root", default=str(default_root()))
    parser.add_argument("--project-file", default=None)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    catalog = commands.add_parser("catalog")
    catalog.add_argument('--details',action='store_true')
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
    sync.add_argument("--app", required=True)
    sync.add_argument("--app-root", required=True, help="独立 App 安装根目录，例如 .agent-apps")
    verify = commands.add_parser("verify")
    verify.add_argument("--version", default=None)
    commands.add_parser("rollback")
    automation = commands.add_parser('automation').add_subparsers(dest='operation',required=True)
    add = automation.add_parser('add')
    add.add_argument('--file',default='-')
    automation.add_parser('list')
    for name in ('show','enable','disable','preview','grant','revoke','run'):
        operation = automation.add_parser(name)
        operation.add_argument('--rule',required=True)
        if name == 'run':
            identifiers=operation.add_mutually_exclusive_group()
            identifiers.add_argument('--invocation-id')
            identifiers.add_argument('--run-id')
            operation.add_argument('--host-mode',choices=('readonly','execute'),default='readonly')
    automation.add_parser('tick')
    worker=automation.add_parser('worker')
    worker.add_argument('--max-ticks',type=int)
    events=commands.add_parser('events').add_subparsers(dest='operation',required=True)
    events.add_parser('list')
    events.add_parser('show').add_argument('--event-id',required=True)
    events.add_parser('publish').add_argument('--file',default='-')
    history=commands.add_parser('history').add_subparsers(dest='operation',required=True)
    history_list=history.add_parser('list')
    history_list.add_argument('--rule')
    history_list.add_argument('--status')
    history.add_parser('show').add_argument('--run-id',required=True)
    resolve=history.add_parser('resolve')
    resolve.add_argument('--request-id',required=True)
    resolve.add_argument('--outcome',choices=('verified_success','verified_failed','abandoned'),required=True)
    resolve.add_argument('--reason-code',required=True)
    resolve.add_argument('--evidence-ref',default='')
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
