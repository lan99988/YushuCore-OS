"""Single governed application boundary shared by local front ends."""

from __future__ import annotations

from dataclasses import asdict
import os
import re
import secrets
from typing import Any, Mapping
from uuid import uuid4
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from capability_plugins.loader import load_manifests
from capability_plugins.registry import PluginRegistry, PluginResolutionError
from capability_plugins.local_record.plugin import LocalRecordPlugin
from capability_plugins.knowledge.plugin import KnowledgePlugin
from knowledge_system.gateway import AgentPolicy
from knowledge_system.gateway.ima_service import ImaKnowledgeGateway
from orchestration import FlowName, UserIntent
from orchestration.executor import Executor
from orchestration.planner import CapabilityPlanner, CapabilityRequest
from runtime_core import AgentDefinition, RuntimeKernel

from .profile import Profile
from .store import LocalStore
from .approval import ApprovalError, ApprovalStore
from .diagnostics import ConnectorDiagnostics
from integrations.ollama import OllamaClient
from .capture_inputs import CaptureInputError, CaptureInputs


_MANIFEST_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "capability_plugins" / "manifests"
_AGENT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_KINDS = ("task", "calendar", "goal", "project", "commitment", "learning", "body",
          "information", "finance", "life_admin", "creation", "interest", "experience")


def _result(status: str, correlation_id: str, *, data: Any = None, error_code: str | None = None,
            source: str = "local", stale: bool = False, approval_id: str | None = None) -> dict[str, Any]:
    result = {"schema_version": 1, "status": status, "correlation_id": correlation_id,
              "data": data, "error_code": error_code, "source": source, "stale": stale}
    if approval_id is not None:
        result["approval_id"] = approval_id
    return result


class YushuApplication:
    def __init__(self, profile: Profile, *, ima_adapter: Any | None = None,
                 ima_sources: Mapping[str, Mapping[str, str]] | None = None) -> None:
        self.profile = profile
        self.store = LocalStore(profile)
        self.approvals = ApprovalStore(profile)
        self.manifests = load_manifests(_MANIFEST_DIR)
        for manifest in self.manifests:
            for schema in (*manifest.input_contract.values(), *manifest.output_contract.values()):
                Draft202012Validator.check_schema(schema)
        self.registry = PluginRegistry.from_manifests(self.manifests)
        self._local_plugin = LocalRecordPlugin(self.store)
        self._ima_adapter = ima_adapter
        self._ima_sources = dict(ima_sources or {})
        self._knowledge_credential = secrets.token_urlsafe(32)

    def _knowledge_gateway(self, agent_id: str) -> ImaKnowledgeGateway:
        return ImaKnowledgeGateway(
            cache_path=self.profile.root / "ima_summary_cache.sqlite3",
            adapter=self._ima_adapter,
            sources=self._ima_sources,
            policies={agent_id: AgentPolicy(
                allowed_folders=tuple(f"ima/{kb_id}" for kb_id in self._ima_sources),
                allowed_domains=tuple(sorted({source["domain"] for source in self._ima_sources.values()})),
                max_sensitivity="level_0",
            )},
            agent_credentials={agent_id: self._knowledge_credential},
        )

    def capabilities(self) -> list[dict[str, Any]]:
        catalog = []
        knowledge_status = self._knowledge_gateway("owner").health()["status"]
        for manifest in self.manifests:
            for name in manifest.provides:
                implemented = manifest.plugin_id in {"local_record", "knowledge"}
                needs_ima = manifest.plugin_id == "knowledge" and name != "knowledge.health"
                available = implemented and (not needs_ima or knowledge_status != "not_configured")
                reason = ("plugin_executor_missing" if not implemented else
                          "not_configured" if not available else None)
                catalog.append({"name": name, "plugin_id": manifest.plugin_id,
                                "effect": manifest.capability_effects.get(name, "unknown"),
                                "status": "ready" if available else "unavailable",
                                "reason_code": reason})
        return sorted(catalog, key=lambda item: item["name"])

    def invoke_capability(self, capability: str, payload: dict[str, Any], *, agent_id: str,
                          correlation_id: str | None = None, dry_run: bool = False,
                          flow: str = "capture") -> dict[str, Any]:
        correlation_id = correlation_id or uuid4().hex
        if not isinstance(agent_id, str) or not _AGENT_ID.fullmatch(agent_id):
            return _result("blocked", correlation_id, error_code="invalid_agent_id")
        if type(payload) is not dict:
            return _result("blocked", correlation_id, error_code="invalid_payload")
        if not isinstance(capability, str) or not capability:
            return _result("blocked", correlation_id, error_code="invalid_capability")
        try:
            flow_name = FlowName(flow)
        except ValueError:
            return _result("blocked", correlation_id, error_code="invalid_flow")
        try:
            manifest = self.registry.by_capability(capability)
        except KeyError:
            return _result("unsupported", correlation_id, error_code="unknown_capability")
        except PluginResolutionError as exc:
            return _result("unavailable", correlation_id, error_code=exc.status)
        if manifest.plugin_id not in {"local_record", "knowledge"}:
            return _result("unavailable", correlation_id, error_code="plugin_executor_missing")
        schema = manifest.input_contract.get(capability)
        if schema is not None:
            try:
                Draft202012Validator(schema).validate(payload)
            except ValidationError:
                return _result("blocked", correlation_id, error_code="invalid_payload")
        if capability in {"local_record.create", "local_record.update"}:
            data = payload.get("data")
            if payload.get("kind") == "commitment" or (
                payload.get("kind") == "calendar" and isinstance(data, dict)
                and (data.get("external_commitment") is True or data.get("fixed_meeting") is True)
            ):
                payload = {**payload, "affects_commitment": True}

        gateway = self._knowledge_gateway(agent_id)
        kernel = RuntimeKernel(
            gateway=gateway, state_path=self.profile.root / "runtime",
            local_model="local-unconfigured", cloud_model="cloud-unconfigured",
            default_network_mode="OFF", plugin_registry=self.registry,
        )
        kernel.register_agent(AgentDefinition(
            agent_id=agent_id, name=agent_id, domain="user", autonomy_level=2,
            risk_level="medium", permissions=tuple(sorted(set(manifest.permissions))),
            handler=lambda context: None,
        ))
        intent = UserIntent(flow=flow_name, text=f"invoke {capability}", confidence=1.0,
                            evidence=("explicit_capability",), correlation_id=correlation_id)
        planning = CapabilityPlanner(self.registry).plan(
            intent, (CapabilityRequest(step_id="invoke", capability=capability, payload=payload),)
        )
        if planning.plan is None:
            code = planning.gaps[0].reason_code if planning.gaps else "planning_failed"
            return _result("blocked", correlation_id, error_code=code)
        plugins = {"local_record": self._local_plugin,
                   "knowledge": KnowledgePlugin(gateway, agent_id=agent_id,
                                                credential=self._knowledge_credential)}
        execution = Executor(kernel, plugins).execute(planning.plan, agent_id, dry_run=dry_run)
        step = execution.steps[0]
        if step.status == "completed":
            data = step.result
            source = data.get("source", "local") if isinstance(data, dict) else "local"
            stale = data.get("stale", False) if isinstance(data, dict) else False
            return _result("completed", correlation_id, data=data, source=source, stale=stale)
        if step.decision is not None and step.decision.approval_required:
            approval_id = self.approvals.request(
                agent_id=agent_id, capability=capability, payload=payload,
                correlation_id=correlation_id,
                target=f"{payload.get('kind', '')}:{payload.get('record_id', '')}",
            )
            return _result("pending_approval", correlation_id,
                           error_code=step.decision.reason_code, approval_id=approval_id)
        return _result("dry_run" if dry_run else step.status, correlation_id,
                       error_code=step.error_code or "execution_blocked",
                       source="ima" if manifest.plugin_id == "knowledge" else "local",
                       stale=manifest.plugin_id == "knowledge")

    def run_flow(self, flow: str, text: str, *, context: Mapping[str, Any] | None = None,
                 agent_id: str = "owner", correlation_id: str | None = None,
                 dry_run: bool = False) -> dict[str, Any]:
        correlation_id = correlation_id or uuid4().hex
        if not isinstance(text, str) or not text.strip():
            return _result("needs_clarification", correlation_id, error_code="empty_input")
        if flow not in {item.value for item in FlowName}:
            return _result("unsupported", correlation_id, error_code="unknown_flow")
        context = dict(context or {})
        invoke = lambda capability, payload: self.invoke_capability(
            capability, payload, agent_id=agent_id, correlation_id=correlation_id,
            dry_run=dry_run, flow=flow)
        if flow == "capture":
            if "file" in context and "url" in context:
                return _result("blocked", correlation_id, error_code="ambiguous_capture_source")
            if "file" in context or "url" in context:
                allowed_hosts = [host.strip() for host in os.environ.get("YUSHU_WEB_ALLOWED_HOSTS", "").split(",")
                                 if host.strip()]
                importer = CaptureInputs(self.profile, allowed_hosts=allowed_hosts)
                try:
                    imported = (importer.read_file(context["file"]) if "file" in context
                                else importer.read_url(context["url"]))
                except (CaptureInputError, TypeError, ValueError) as exc:
                    return _result("blocked", correlation_id,
                                   error_code=exc.code if isinstance(exc, CaptureInputError) else "invalid_capture_source")
                return invoke("local_record.create", {"kind": "information", "data": {
                    "title": text.strip(), "content": imported["content"],
                    "source": imported["source"], "source_ref": imported["source_ref"]}})
            kind = context.get("kind") or ("task" if any(word in text for word in ("待办", "提醒", "记得")) else "information")
            return invoke("local_record.create", {"kind": kind, "data": {"title": text.strip(),
                    "source": "user_input", **context.get("data", {})},
                    "idempotency_key": context.get("idempotency_key")})
        if flow == "plan":
            return invoke("local_record.create", {"kind": "goal", "data": {"title": text.strip(),
                    "status": "draft", **context.get("data", {})}})
        if flow == "adjust":
            if not all(key in context for key in ("kind", "record_id", "data", "expected_version")):
                return _result("needs_clarification", correlation_id, error_code="adjust_target_required")
            return invoke("local_record.update", dict(context))
        if flow == "today":
            tasks = invoke("local_record.list", {"kind": "task"})
            events = invoke("local_record.list", {"kind": "calendar"})
            if tasks["status"] != "completed" or events["status"] != "completed":
                return _result("unavailable", correlation_id, error_code="authoritative_source_unavailable")
            return _result("completed", correlation_id, data={"tasks": tasks["data"]["records"],
                    "events": events["data"]["records"]})
        if flow == "review":
            counts: dict[str, int] = {}
            unavailable: list[str] = []
            for kind in _KINDS:
                response = invoke("local_record.list", {"kind": kind})
                if response["status"] == "completed":
                    counts[kind] = len(response["data"]["records"])
                else:
                    unavailable.append(kind)
            return _result("partial" if unavailable else "completed", correlation_id,
                           data={"counts": counts, "unavailable_sources": unavailable,
                                 "analysis": "本地记录数量汇总；尚未生成因果分析。"})
        matches = []
        for kind in _KINDS:
            response = invoke("local_record.list", {"kind": kind})
            if response["status"] == "completed":
                matches.extend(record for record in response["data"]["records"]
                               if text.casefold() in str(record["data"]).casefold())
        knowledge = invoke("knowledge.search", {"query": text.strip()})
        knowledge_status = ("online" if knowledge["status"] == "completed"
                            else knowledge.get("error_code") or knowledge["status"])
        return _result("completed" if knowledge["status"] == "completed" else "partial",
                       correlation_id, data={"local_matches": matches,
                                             "knowledge": knowledge["data"] if knowledge["status"] == "completed" else None,
                                             "knowledge_status": knowledge_status},
                       source="mixed" if knowledge["status"] == "completed" else "local",
                       stale=knowledge.get("stale", False))

    def approve(self, approval_id: str, *, reviewer: str) -> dict[str, Any]:
        if not isinstance(approval_id, str) or not approval_id:
            return _result("blocked", uuid4().hex, error_code="invalid_approval_id")
        try:
            action = self.approvals.claim(approval_id, reviewer=reviewer)
        except ApprovalError as exc:
            return _result("blocked", uuid4().hex, error_code=str(exc))
        if action["capability"] not in {"local_record.create", "local_record.update"}:
            self.approvals.finish(approval_id, succeeded=False)
            return _result("blocked", action["correlation_id"], error_code="approved_executor_unavailable")
        payload = dict(action["payload"])
        if action["capability"] == "local_record.create" and not payload.get("idempotency_key"):
            payload["idempotency_key"] = f"approval:{approval_id}"
        try:
            data = self._local_plugin.invoke(action["capability"], payload,
                {"agent_id": action["agent_id"], "correlation_id": action["correlation_id"]})
        except Exception:
            self.approvals.finish(approval_id, succeeded=False)
            return _result("failed", action["correlation_id"], error_code="approved_action_failed")
        self.approvals.finish(approval_id, succeeded=True)
        return _result("completed", action["correlation_id"], data=data, source="local")

    def diagnose(self, *, live: bool = False) -> dict[str, Any]:
        gateway = self._knowledge_gateway("owner")
        probes = {"ima": (lambda: gateway.health(probe=True)) if self._ima_adapter is not None else None,
                  "feishu": None, "garmin": None, "ollama": OllamaClient(timeout=3).health}
        return ConnectorDiagnostics(probes).run(live=live)

    def health(self, *, probe: bool = False) -> dict[str, Any]:
        gateway = self._knowledge_gateway("owner")
        return {"schema_version": 1, "status": "available", "profile": self.profile.profile_id,
                "knowledge": gateway.health(probe=probe), "authorities": dict(self.profile.authorities)}
