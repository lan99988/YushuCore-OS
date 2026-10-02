"""Core-only immutable workflow planning types."""

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any

from yushuos_sdk.contracts import Request, Result, thaw


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    capability: str
    request: Request
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    project_ref: str
    steps: tuple[PlanStep, ...]
    fingerprint: str

    @classmethod
    def create(cls, project_ref: str, steps: list[PlanStep]) -> "ExecutionPlan":
        ids = [step.step_id for step in steps]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("执行计划必须包含唯一且非空的步骤")
        known = set(ids)
        for step in steps:
            if not isinstance(step.step_id, str) or not _ID.fullmatch(step.step_id) or step.capability != step.request.capability:
                raise ValueError("计划步骤标识或能力与请求不匹配")
            if len(step.depends_on) != len(set(step.depends_on)) or not set(step.depends_on) <= known or step.step_id in step.depends_on:
                raise ValueError("计划依赖引用无效")
        _topological_order(steps)
        body = {
            "project_ref": project_ref,
            "steps": [
                {"step_id": s.step_id, "capability": s.capability, "request": s.request.to_dict(), "depends_on": list(s.depends_on)}
                for s in steps
            ],
        }
        digest = sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()
        return cls(plan_id=f"plan-{digest[:24]}", project_ref=project_ref, steps=tuple(steps), fingerprint=digest)


def _topological_order(steps: tuple[PlanStep, ...] | list[PlanStep]) -> tuple[PlanStep, ...]:
    indexed = {step.step_id: step for step in steps}
    remaining = {step.step_id: set(step.depends_on) for step in steps}
    result: list[PlanStep] = []
    while remaining:
        ready = sorted(step_id for step_id, deps in remaining.items() if not deps)
        if not ready:
            raise ValueError("计划包含循环依赖")
        for step_id in ready:
            result.append(indexed[step_id])
            remaining.pop(step_id)
            for deps in remaining.values():
                deps.discard(step_id)
    return tuple(result)


__all__ = ["Request", "Result", "PlanStep", "ExecutionPlan", "thaw"]
