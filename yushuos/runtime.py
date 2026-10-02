"""Manifest-driven Core runtime; domain work stays in independently callable plugins."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

from . import __version__
from .config import load_config
from .manifest import CapabilitySpec, validate_schema as _check_schema
from .models import ExecutionPlan, PlanStep, Request, Result, _topological_order, thaw
from .registry import CapabilityBinding, PluginRegistry, discover_roots
from .state import StateStore


_STATUS = {"preview", "succeeded", "partial", "verification_pending", "unknown", "failed", "unavailable", "needs_clarification"}
_PLACEHOLDER = re.compile(r"\{(python|plugin_root|config_root|project_root|plugin_id|plugin_version|capability|mode|host_mode)\}")


class PluginRunner:
    def __init__(self, config: dict[str, Any], *, run=None):
        self.config = config
        self.run = run or subprocess.run

    def invoke(self, binding: CapabilityBinding, request: Request, *, mode: str, host_mode: str) -> Result:
        spec, capability = binding.plugin, binding.capability
        command = spec.runner["command"]
        python = self.config.get("runtime", {}).get("python_executable") or sys.executable
        project_file = self.config.get("_project_file", "")
        values = {
            "python": python, "plugin_root": str(spec.root), "config_root": self.config["_config_root"],
            "project_root": str(Path(project_file).parent) if project_file else "",
            "plugin_id": spec.plugin_id, "plugin_version": spec.version, "capability": capability.name,
            "mode": mode, "host_mode": host_mode,
        }

        def expand(token: str) -> str:
            unknown = re.search(r"\{[^{}]+\}", token)
            if unknown and not _PLACEHOLDER.fullmatch(unknown.group(0)):
                raise ValueError("runner 参数包含未支持的变量")
            return _PLACEHOLDER.sub(lambda match: values[match.group(1)], token)

        try:
            args = [expand(token) for token in (*command, *capability.runner_args)]
            if not args or any(not value for value in args):
                return Result("unavailable", request.request_id, "插件执行命令未完成绑定")
            payload = {
                "protocol": "json-stdio-v1", "action": "invoke", "plugin_id": spec.plugin_id,
                "plugin_version": spec.version, "capability": capability.name, "capability_effect": capability.effect,
                "request": request.to_dict(), "mode": mode, "host_mode": host_mode,
                "config_root": self.config["_config_root"],
                "project_file": project_file,
                "state_ledger_path": self.config.get("_ledger_path", ""),
                "app_binding": self.config.get("bindings", {}).get("apps", {}).get(spec.plugin_id, {}),
                "plugin_config": self.config.get("plugins", {}).get("config", {}).get(spec.plugin_id, {}),
                "data_path": str(self._data_path(spec, create=capability.effect in {"internal_write", "external_write"})),
            }
            env_names = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA")
            env = {name: os.environ[name] for name in env_names if name in os.environ}
            env["PYTHONUTF8"] = "1"
            env["YUSHUOS_HOME"] = self.config["_config_root"]
            env["YUSHUOS_PLUGIN_ID"] = spec.plugin_id
            env["YUSHUOS_PLUGIN_VERSION"] = spec.version
            sdk_root = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = sdk_root
            process = self.run(
                args, input=json.dumps(payload, ensure_ascii=False, allow_nan=False),
                capture_output=True, text=True, encoding="utf-8", timeout=spec.runner["timeout_seconds"],
                cwd=str(spec.root), env=env,
            )
        except subprocess.TimeoutExpired:
            status = "unknown" if capability.effect in {"internal_write", "external_write"} and mode == "execute" and host_mode == "execute" else "unavailable"
            return Result(status, request.request_id, "插件调用超时；写入结果需按原请求 ID 核对")
        except (OSError, ValueError, TypeError):
            return Result("unavailable", request.request_id, "插件执行器无法启动或绑定无效")
        try:
            result = json.loads(process.stdout, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("JSON 数字无效")))
            if not isinstance(result, dict) or set(result) - {"status", "request_id", "message", "resource", "data", "error"}:
                raise ValueError("插件结果格式无效")
            response = Result(**result)
            if response.request_id != request.request_id or response.status not in _STATUS:
                raise ValueError("插件结果与请求不匹配")
            if (not isinstance(response.message, str) or not isinstance(response.resource, Mapping)
                    or response.error is not None and not isinstance(response.error, Mapping)):
                raise ValueError("插件结果字段类型无效")
            if process.returncode and response.status in {"succeeded", "preview"}:
                raise ValueError("插件返回状态与退出码不匹配")
            if response.status in {"succeeded", "preview"}:
                schema_error = _check_schema(capability.outputs, response.data if response.data is not None else {})
                if schema_error:
                    raise ValueError("插件输出未通过 Schema 校验")
            return response
        except (ValueError, TypeError, KeyError):
            status = "unknown" if capability.effect in {"internal_write", "external_write"} and mode == "execute" and host_mode == "execute" else "unavailable"
            return Result(status, request.request_id, "插件结果未通过 JSON 契约校验")

    def _data_path(self, spec, *, create: bool) -> Path:
        root = Path(self.config["_config_root"]).resolve()
        plugin_data_root = root / "plugin-data"
        base = plugin_data_root / spec.plugin_id
        target = base / (Path(spec.data_path) if spec.data_path else Path())
        if not target.resolve().is_relative_to(base.resolve()):
            raise ValueError("插件数据路径越界")
        candidates = [plugin_data_root, base]
        relative = target.relative_to(base)
        cursor = base
        for part in relative.parts:
            cursor = cursor / part
            candidates.append(cursor)
        if any(path.exists() and path.is_symlink() for path in candidates):
            raise ValueError("插件数据路径包含链接")
        if create:
            target.mkdir(parents=True, exist_ok=True)
        return target


def _target_value(target: Mapping[str, Any], path: str) -> Any:
    value: Any = target
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


_RESOURCE_REFERENCE_KEYS = frozenset({
    "id", "type", "kind", "ref", "version", "provider", "external_id", "resource_key",
    "calendar_id", "event_id", "task_id", "task_guid", "document_id", "record_id",
})


def _checkpoint_resource_refs(resource: Mapping[str, Any]) -> dict[str, str | int | bool | None]:
    """Keep only simple identifiers in workflow history, never arbitrary plugin payloads."""
    safe: dict[str, str | int | bool | None] = {}
    for key, value in resource.items():
        if key in _RESOURCE_REFERENCE_KEYS and (value is None or isinstance(value, (str, int, bool))):
            if not isinstance(value, str) or (len(value) <= 512 and not any(char in value for char in "\r\n?#") and "://" not in value):
                safe[key] = value
    return safe


class CoreRuntime:
    def __init__(self, config_root=None, *, project_file=None, runner=None):
        self.config = load_config(config_root, project_file=project_file)
        self.registry = PluginRegistry(discover_roots(self.config), self.config)
        ledger_path = self.config.get("state", {}).get("ledger_path", "")
        if ledger_path:
            selected_ledger = Path(ledger_path).expanduser()
            if not selected_ledger.is_absolute():
                selected_ledger = Path(self.config["_config_root"]) / selected_ledger
            self.config["_ledger_path"] = str(selected_ledger.absolute())
            self.state = StateStore(selected_ledger)
        else:
            self.config["_ledger_path"] = ""
            self.state = None
        self.runner = runner or PluginRunner(self.config)

    def _binding(self, capability: str) -> CapabilityBinding | None:
        return self.registry.resolve(capability)

    def _request(self, value: dict[str, Any]) -> Request:
        allowed = {"request_id", "capability", "intent", "fields", "target", "project_ref"}
        if not isinstance(value, dict) or set(value) - allowed or not {"request_id", "capability", "intent"} <= set(value):
            raise ValueError("请求字段缺失或包含未知字段")
        request = Request(**value)
        configured_project = self.config.get("project_ref", "")
        if (configured_project or request.project_ref) and request.project_ref != configured_project:
            raise ValueError("请求项目与加载的项目配置不匹配")
        return request

    def parse(self, text: str) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            return {"status": "needs_clarification", "message": "需要非空输入"}
        return self.registry.route(text.strip())

    def _gate(self, binding: CapabilityBinding, request: Request, *, mode: str, host_mode: str) -> Result | None:
        capability = binding.capability
        if request.capability != capability.name:
            return Result("unavailable", request.request_id, "插件能力与请求不一致")
        if request.intent not in capability.intents:
            return Result("needs_clarification", request.request_id, "请求意图未由插件清单允许")
        schema_error = _check_schema(capability.inputs, thaw(request.fields))
        if schema_error:
            return Result("needs_clarification", request.request_id, schema_error)
        resources = self.config.get("bindings", {}).get("resources", {})
        for target_path, resource_key in capability.resource_scopes:
            expected = resources.get(resource_key)
            actual = _target_value(request.target, target_path)
            if not expected:
                return Result("unavailable", request.request_id, "插件所需资源未绑定",
                              error={"reason": "resource_scope_unbound", "scope": resource_key})
            if actual != expected:
                return Result("unavailable", request.request_id, "请求目标超出已绑定资源范围",
                              error={"reason": "resource_scope_mismatch", "scope": resource_key})
        if capability.effect in {"internal_write", "external_write"}:
            if mode != "execute" or host_mode != "execute":
                if self.config["execution"]["preview_business_writes"] is False:
                    return Result("preview", request.request_id, "当前模式只生成预览，尚未写入")
            if self.state is None or not self.state.path.is_file():
                return Result("unavailable", request.request_id, "尚未绑定现存共享操作台账")
        if host_mode not in {"readonly", "ask", "plan", "quick", "execute"} or mode not in {"preview", "execute"}:
            return Result("unavailable", request.request_id, "执行模式无效")
        return None

    def invoke(self, request_value: dict[str, Any], *, mode: str = "preview", host_mode: str = "readonly") -> Result:
        request = self._request(request_value)
        binding = self._binding(request.capability)
        if binding is None:
            return Result("unavailable", request.request_id, "插件或能力未就绪", error={"reasons": self.registry.unavailable_reasons(request.capability)})
        gate = self._gate(binding, request, mode=mode, host_mode=host_mode)
        if gate:
            return gate
        receipt = self.state.receipt(request.request_id) if self.state else None
        if receipt:
            if receipt["fingerprint"] != request.fingerprint():
                return Result("needs_clarification", request.request_id, "同一请求 ID 已用于其他内容")
            if receipt["status"] in {"unknown", "verifying", "dispatched"}:
                return Result("unknown", request.request_id, "已有请求结果待核对；本体不会盲目重试", resource=(receipt.get("receipt") or {}).get("resource", {}))
            if receipt.get("receipt"):
                return Result(**receipt["receipt"])
        return self.runner.invoke(binding, request, mode=mode, host_mode=host_mode)

    def build_plan(self, value: dict[str, Any]) -> ExecutionPlan:
        if not isinstance(value, dict) or set(value) - {"project_ref", "steps"}:
            raise ValueError("计划字段无效")
        project_ref = value.get("project_ref", self.config.get("project_ref", ""))
        if not isinstance(project_ref, str):
            raise ValueError("project_ref 必须是字符串")
        steps_raw = value.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValueError("计划必须包含步骤")
        steps = []
        for item in steps_raw:
            if not isinstance(item, dict) or set(item) - {"step_id", "capability", "intent", "fields", "target", "request_id", "depends_on"}:
                raise ValueError("计划步骤格式无效")
            capability = item.get("capability")
            request = self._request({"request_id": item.get("request_id"), "capability": capability,
                                     "intent": item.get("intent"), "fields": item.get("fields", {}),
                                     "target": item.get("target", {}), "project_ref": project_ref})
            deps = item.get("depends_on", [])
            if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
                raise ValueError("depends_on 必须是字符串数组")
            steps.append(PlanStep(item.get("step_id"), capability, request, tuple(deps)))
        return ExecutionPlan.create(project_ref, steps)

    def plan(self, value: dict[str, Any]) -> dict[str, Any]:
        plan = self.build_plan(value)
        ordered = _topological_order(plan.steps)
        entries = []
        for step in ordered:
            binding = self._binding(step.capability)
            gate = self._gate(binding, step.request, mode="execute", host_mode="execute") if binding else None
            reasons = self.registry.unavailable_reasons(step.capability) if binding is None else (
                [gate.error.get("reason", gate.message or gate.status)] if gate and gate.error
                else [gate.message or gate.status] if gate else []
            )
            entries.append({
                "step_id": step.step_id, "request_id": step.request.request_id,
                "capability": step.capability, "depends_on": list(step.depends_on),
                "status": "ready" if binding and gate is None else "unavailable",
                "provider": binding.plugin.plugin_id if binding else None,
                "provider_version": binding.plugin.version if binding else None,
                "effect": binding.capability.effect if binding else None,
                "expected_changes": ({
                    "effect": binding.capability.effect,
                    "business_write_required": binding.capability.effect in {"internal_write", "external_write"},
                    "target_fields": sorted(step.request.target.keys()),
                    "resource_scopes": [scope for _, scope in binding.capability.resource_scopes],
                } if binding else None),
                "reasons": reasons,
            })
        return {"status": "preview", "plan_id": plan.plan_id, "fingerprint": plan.fingerprint,
                "project_ref": plan.project_ref, "steps": entries, "write_performed": False}

    def execute_plan(self, value: dict[str, Any], *, host_mode: str) -> dict[str, Any]:
        plan = self.build_plan(value)
        if host_mode != "execute":
            return self.plan(value)
        bindings: dict[str, CapabilityBinding] = {}
        provider_versions: dict[str, tuple[str, str]] = {}
        for step in plan.steps:
            binding = self._binding(step.capability)
            if binding is None:
                return {"status": "unavailable", "plan_id": plan.plan_id,
                        "message": f"步骤 {step.step_id} 的能力未就绪", "reasons": self.registry.unavailable_reasons(step.capability)}
            gate = self._gate(binding, step.request, mode="execute", host_mode=host_mode)
            if gate:
                return {"status": gate.status, "plan_id": plan.plan_id, "step_id": step.step_id, "message": gate.message}
            bindings[step.step_id] = binding
            provider_versions[step.step_id] = (binding.plugin.plugin_id, binding.plugin.version)
        if self.state is None:
            return {"status": "unavailable", "plan_id": plan.plan_id, "message": "尚未绑定共享操作台账"}
        state = self.state.begin_plan(plan, provider_versions)
        previous = {step["step_id"]: step for step in state["steps"]}
        statuses: dict[str, str] = {}
        output: list[dict[str, Any]] = []
        for step in _topological_order(plan.steps):
            saved = previous[step.step_id]
            if saved["status"] == "succeeded":
                statuses[step.step_id] = "succeeded"
                output.append({"step_id": step.step_id, "status": "succeeded", "resource": saved["result_refs"]})
                continue
            if any(statuses.get(dep) != "succeeded" for dep in step.depends_on):
                self.state.transition_step(plan.plan_id, step.step_id, "blocked", error_code="dependency_not_succeeded")
                statuses[step.step_id] = "blocked"
                output.append({"step_id": step.step_id, "status": "blocked", "error_code": "dependency_not_succeeded"})
                continue
            prior_receipt = self.state.receipt(step.request.request_id)
            if saved["status"] in {"running", "unknown", "verification_pending"}:
                if prior_receipt is None or prior_receipt["status"] in {"dispatched", "unknown", "verifying"}:
                    self.state.transition_step(plan.plan_id, step.step_id, "unknown", error_code="existing_result_requires_readback")
                    statuses[step.step_id] = "unknown"
                    output.append({"step_id": step.step_id, "status": "unknown", "error_code": "existing_result_requires_readback"})
                    continue
            self.state.transition_step(plan.plan_id, step.step_id, "running")
            result = self.invoke(step.request.to_dict(), mode="execute", host_mode=host_mode)
            if result.status == "succeeded":
                self.state.transition_step(plan.plan_id, step.step_id, "succeeded", resource=_checkpoint_resource_refs(result.resource))
            elif result.status == "verification_pending":
                self.state.transition_step(plan.plan_id, step.step_id, "verification_pending", resource=_checkpoint_resource_refs(result.resource))
            elif result.status == "unknown":
                self.state.transition_step(plan.plan_id, step.step_id, "unknown", resource=_checkpoint_resource_refs(result.resource), error_code="provider_result_unknown")
            else:
                self.state.transition_step(plan.plan_id, step.step_id, "failed", error_code=result.status)
            statuses[step.step_id] = result.status
            output.append({"step_id": step.step_id, **result.to_dict()})
            if result.status not in {"succeeded"}:
                # Never continue to side-effecting descendants after an uncertain result.
                break
        terminal = set(statuses.values())
        status = "succeeded" if terminal == {"succeeded"} else "unknown" if "unknown" in terminal or "verification_pending" in terminal else "partial" if "succeeded" in terminal else "failed"
        self.state.finish_plan(plan.plan_id, status)
        return {"status": status, "plan_id": plan.plan_id, "steps": output}

    def resume(self, request_value: dict[str, Any], *, host_mode: str) -> Result:
        request = self._request(request_value)
        if self.state is None:
            return Result("unavailable", request.request_id, "尚未绑定共享操作台账")
        receipt = self.state.receipt(request.request_id)
        if not receipt:
            return Result("unavailable", request.request_id, "找不到可恢复的原请求收据")
        if receipt["fingerprint"] != request.fingerprint():
            return Result("needs_clarification", request.request_id, "恢复请求与原收据内容不一致")
        if receipt["status"] in {"unknown", "dispatched", "verifying"}:
            return Result("unknown", request.request_id, "结果未知，必须先核对远端；不会重复提交")
        if receipt["receipt"] and receipt["status"] not in {"verification_pending"}:
            return Result(**receipt["receipt"])
        return self.invoke(request.to_dict(), mode="execute", host_mode=host_mode)

    def resume_plan(self, value: dict[str, Any], *, host_mode: str) -> dict[str, Any]:
        plan = self.build_plan(value)
        if self.state is None:
            return {"status": "unavailable", "plan_id": plan.plan_id, "message": "尚未绑定共享操作台账"}
        workflow = self.state.workflow(plan.plan_id)
        if workflow is None:
            return {"status": "unavailable", "plan_id": plan.plan_id, "message": "找不到已保存的流程；不会将新计划当作恢复任务"}
        if workflow["run"]["fingerprint"] != plan.fingerprint:
            return {"status": "needs_clarification", "plan_id": plan.plan_id, "message": "恢复内容与已保存流程不一致"}
        if workflow["run"]["status"] == "succeeded":
            return {"status": "succeeded", "plan_id": plan.plan_id, "steps": workflow["steps"], "resumed": False}
        if workflow["run"]["status"] == "failed":
            return {"status": "failed", "plan_id": plan.plan_id, "steps": workflow["steps"], "resumed": False,
                    "message": "流程已明确失败；创建新请求 ID 和计划后再试"}
        if host_mode != "execute":
            return {"status": "preview", "plan_id": plan.plan_id, "message": "恢复需要宿主显式执行授权；尚未调用插件"}
        result = self.execute_plan(value, host_mode=host_mode)
        result["resumed"] = True
        return result

    def doctor(self) -> dict[str, Any]:
        config_root = Path(self.config["_config_root"])
        ledger = self.config.get("_ledger_path", "")
        active_state_path = config_root / "active.json"
        active_version = None
        release_status = "unavailable"
        if active_state_path.is_file() and not active_state_path.is_symlink():
            try:
                active_state = json.loads(active_state_path.read_text(encoding="utf-8-sig"))
                if isinstance(active_state, dict) and isinstance(active_state.get("active"), str):
                    active_version = active_state["active"]
                    from .deployment import verify_release
                    release_status = "verified" if verify_release(config_root, active_version)["verified"] else "failed"
            except (OSError, ValueError, TypeError):
                release_status = "failed"
        host_state_path = config_root / "host-installs.json"
        host_state = {"hosts": {}}
        if host_state_path.is_file() and not host_state_path.is_symlink():
            try:
                value = json.loads(host_state_path.read_text(encoding="utf-8-sig"))
                if isinstance(value, dict) and isinstance(value.get("hosts"), dict):
                    host_state = value
            except (OSError, ValueError, TypeError):
                pass
        host_installs: dict[str, str] = {}
        for host, record in host_state["hosts"].items():
            if not isinstance(host, str) or not isinstance(record, dict):
                continue
            target = Path(record.get("target", ""))
            if not target.is_absolute() or target.is_symlink() or not target.is_file():
                host_installs[host] = "missing_or_invalid"
            else:
                try:
                    host_installs[host] = "verified" if hashlib.sha256(target.read_bytes()).hexdigest() == record.get("installed_sha256") else "modified"
                except OSError:
                    host_installs[host] = "missing_or_invalid"
        return {
            "core_version": __version__, "api_version": 2,
            "config_present": (config_root / "config.yaml").is_file(),
            "config_root_available": config_root.exists(),
            "ledger_bound": bool(ledger), "ledger_exists": bool(ledger and Path(ledger).is_file()),
            "active_release": active_version, "release_status": release_status,
            "host_installs": host_installs,
            "plugin_count": len(self.registry.plugins), "manifest_errors": self.registry.errors,
            "host_modes": {"workbuddy": self.config["hosts"]["workbuddy"], "codex": self.config["hosts"]["codex"]},
            "writes_default_to_preview": self.config["core"]["default_mode"] == "preview",
        }
