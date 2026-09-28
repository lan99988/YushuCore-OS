"""Human-facing and automation-facing command line for one local profile."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from integrations.ima import ImaAdapter
from integrations.settings import IntegrationConfigError

from .application import YushuApplication
from .profile import Profile, ProfileError
from .migration import LegacyMigrator


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yushu")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--json", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="初始化本地 Profile")
    commands.add_parser("health", help="检查本地核心和知识接入")
    diagnose = commands.add_parser("diagnose", help="报告外部接入状态；默认不发网络请求")
    diagnose.add_argument("--live", action="store_true", help="对已装配接入执行只读探测")
    commands.add_parser("capabilities", help="列出所有已登记能力及可用性")
    run = commands.add_parser("run", help="运行 Capture/Plan/Today/Adjust/Review/Explore")
    run.add_argument("flow", choices=("capture", "plan", "today", "adjust", "review", "explore"))
    run.add_argument("text")
    run.add_argument("--kind")
    run.add_argument("--file", help="Profile imports 目录内的相对路径（txt/md）")
    run.add_argument("--url", help="已加入 YUSHU_WEB_ALLOWED_HOSTS 的 HTTPS 页面")
    run.add_argument("--context-json", default="{}")
    run.add_argument("--agent", default="owner")
    run.add_argument("--dry-run", action="store_true")
    invoke = commands.add_parser("invoke", help="调用独立能力")
    invoke.add_argument("capability")
    invoke.add_argument("payload_json")
    invoke.add_argument("--agent", default="owner")
    invoke.add_argument("--dry-run", action="store_true")
    commands.add_parser("approvals", help="列出待人工审批的动作")
    approve = commands.add_parser("approve", help="主人确认并执行一项待审动作")
    approve.add_argument("approval_id")
    approve.add_argument("--confirm", action="store_true", help="确认该动作及目标")
    commands.add_parser("agent-handoff", help="生成不含凭证的 Agent 接手说明")
    backup = commands.add_parser("backup", help="生成一致性 SQLite 备份")
    backup.add_argument("destination", type=Path)
    restore = commands.add_parser("restore", help="校验并恢复 SQLite 备份，保留覆盖前副本")
    restore.add_argument("source", type=Path)
    restore.add_argument("--confirm", action="store_true")
    migrate_preview = commands.add_parser("migrate-preview", help="只读预览旧业务库或知识归档")
    migrate_preview.add_argument("source_type", choices=("information", "knowledge"))
    migrate_preview.add_argument("source", type=Path)
    migrate_execute = commands.add_parser("migrate-execute", help="先备份再幂等导入旧业务数据")
    migrate_execute.add_argument("source_type", choices=("information",))
    migrate_execute.add_argument("source", type=Path)
    migrate_execute.add_argument("--confirm", action="store_true")
    commands.add_parser("mcp", help="启动本地 stdio MCP 服务")
    return parser


def _app(profile: Profile) -> YushuApplication:
    kb_ids = [item.strip() for item in os.environ.get("YUSHU_IMA_KB_IDS", "").split(",") if item.strip()]
    sources = {kb_id: {"domain": "general", "sensitivity": "level_0"} for kb_id in kb_ids}
    adapter = None
    if sources:
        try:
            adapter = ImaAdapter(network_mode="ASSIST")
        except IntegrationConfigError:
            pass
    return YushuApplication(profile, ima_adapter=adapter, ima_sources=sources)


def _parse_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object")
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            profile = Profile.initialize(args.profile, home=args.home)
            output: Any = {"schema_version": 1, "status": "completed", "profile": profile.profile_id,
                           "authorities": dict(profile.authorities)}
        else:
            profile = Profile.open(args.profile, home=args.home)
            app = _app(profile)
            if args.command == "health":
                output = app.health()
            elif args.command == "diagnose":
                output = {"schema_version": 1, "status": "completed", "data": app.diagnose(live=args.live)}
            elif args.command == "capabilities":
                output = {"schema_version": 1, "status": "completed", "data": app.capabilities()}
            elif args.command == "run":
                context = _parse_object(args.context_json)
                if args.kind:
                    context["kind"] = args.kind
                if args.file:
                    context["file"] = args.file
                if args.url:
                    context["url"] = args.url
                output = app.run_flow(args.flow, args.text, context=context,
                                      agent_id=args.agent, dry_run=args.dry_run)
            elif args.command == "invoke":
                output = app.invoke_capability(args.capability, _parse_object(args.payload_json),
                                               agent_id=args.agent, dry_run=args.dry_run)
            elif args.command == "agent-handoff":
                output = {"schema_version": 1, "status": "completed", "profile": profile.profile_id,
                          "mcp_transport": "stdio", "command": "yushu --profile " + profile.profile_id + " mcp",
                          "knowledge_source": "ima", "authorities": dict(profile.authorities),
                          "capability_count": len(app.capabilities())}
            elif args.command == "approvals":
                output = {"schema_version": 1, "status": "completed", "data": app.approvals.list_pending()}
            elif args.command == "approve":
                if args.confirm:
                    output = app.approve(args.approval_id, reviewer="owner")
                else:
                    output = {"schema_version": 1, "status": "blocked",
                              "error_code": "explicit_confirmation_required"}
            elif args.command == "backup":
                checksum = app.store.backup(args.destination)
                output = {"schema_version": 1, "status": "completed", "path": str(args.destination.resolve()),
                          "sha256": checksum}
            elif args.command == "restore":
                if args.confirm:
                    rescue = app.store.restore(args.source)
                    output = {"schema_version": 1, "status": "completed",
                              "pre_restore_backup": str(rescue)}
                else:
                    output = {"schema_version": 1, "status": "blocked",
                              "error_code": "explicit_confirmation_required"}
            elif args.command == "migrate-preview":
                migrator = LegacyMigrator(app.store)
                details = (migrator.preview_information(args.source) if args.source_type == "information"
                           else migrator.preview_knowledge(args.source))
                output = {"schema_version": 1, "status": "completed", "data": details}
            elif args.command == "migrate-execute":
                if args.confirm:
                    details = LegacyMigrator(app.store).import_information(args.source)
                    output = {"schema_version": 1, "status": "completed", "data": details}
                else:
                    output = {"schema_version": 1, "status": "blocked",
                              "error_code": "explicit_confirmation_required"}
            elif args.command == "mcp":
                from .mcp_server import serve_stdio
                serve_stdio(app)
                return 0
            else:
                raise ValueError("unsupported command")
    except (ProfileError, ValueError, FileExistsError, json.JSONDecodeError) as exc:
        output = {"schema_version": 1, "status": "blocked", "error_code": type(exc).__name__}
        code = 2
    else:
        code = 0
    if args.json:
        print(json.dumps(output, ensure_ascii=True, sort_keys=True))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return code
