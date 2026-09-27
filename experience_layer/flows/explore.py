from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re
from typing import Any

from orchestration import CapabilityRequest, FlowName, UserIntent

from experience_layer.contracts import ExperienceItem, ExperienceRequest, ExperienceResponse


_SAFE_REASON = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class ExploreFlow:
    """Answer personal questions through one governed knowledge capability."""

    def __init__(self, planner: Any, executor: Any, *, agent_id: str) -> None:
        if not callable(getattr(planner, "plan", None)):
            raise TypeError("planner must provide plan")
        if not callable(getattr(executor, "execute", None)):
            raise TypeError("executor must provide execute")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id is required")
        self._planner = planner
        self._executor = executor
        self._agent_id = agent_id

    def run(
        self, request: ExperienceRequest, intent: UserIntent
    ) -> ExperienceResponse:
        if not isinstance(request, ExperienceRequest):
            raise TypeError("request must be an ExperienceRequest")
        if not isinstance(intent, UserIntent) or intent.flow is not FlowName.EXPLORE:
            raise ValueError("explore flow requires an Explore intent")

        time_range = request.context.get("time_range")
        interest_id = request.context.get("interest_id")
        reviewing_interest = isinstance(interest_id, str) and bool(interest_id.strip())
        payload = (
            {"interest_id": interest_id.strip()}
            if reviewing_interest
            else {"query": request.text}
        )
        if isinstance(time_range, str) and time_range.strip():
            if not reviewing_interest:
                payload["time_range"] = time_range
        step_id = "explore-interest" if reviewing_interest else "explore-knowledge"
        capability = "interest.review" if reviewing_interest else "knowledge.search"
        planning = self._planner.plan(
            intent,
            (CapabilityRequest(step_id, capability, payload),),
            assumptions=(
                "探索只读取已授权知识或已批准的兴趣事件，不直接执行行动。",
                "结论必须同时展示证据来源、时间范围和置信度。",
            ),
        )
        if planning.plan is None or planning.gaps:
            gaps = tuple(planning.gaps)
            reason = _safe_reason(gaps[0].reason_code) if gaps else "planning_unavailable"
            return ExperienceResponse(
                flow=FlowName.EXPLORE,
                status="blocked",
                uncertainties=(
                    ExperienceItem(
                        item_id="explore-planning-gap",
                        title="探索所需的数据暂不可用。",
                        reason_code=reason,
                    ),
                ),
            )

        execution = self._executor.execute(
            planning.plan,
            agent_id=self._agent_id,
            dry_run=request.dry_run,
        )
        step = next(
            (item for item in execution.steps if item.step_id == step_id),
            None,
        )
        if step is None or step.status != "completed":
            reason = _safe_reason(
                getattr(step, "error_code", None)
                or getattr(step, "status", None)
                or "step_result_missing"
            )
            return ExperienceResponse(
                flow=FlowName.EXPLORE,
                status="blocked",
                uncertainties=(
                    ExperienceItem(
                        item_id="explore-source-unavailable",
                        title="探索数据源暂不可用。",
                        reason_code=reason,
                    ),
                ),
            )

        records = _items(step.result)
        findings: list[ExperienceItem] = []
        invalid_count = 0
        for index, item in enumerate(records, start=1):
            finding = _finding(item, index, time_range)
            if finding is None:
                invalid_count += 1
            else:
                findings.append(finding)
        if not findings:
            reason = "invalid_evidence_data" if invalid_count else "insufficient_evidence"
            return ExperienceResponse(
                flow=FlowName.EXPLORE,
                status="needs_clarification",
                uncertainties=(
                    ExperienceItem(
                        item_id="explore-insufficient-evidence",
                        title="当前证据不足，无法形成可靠结论。",
                        reason_code=reason,
                    ),
                ),
            )

        suggestions: tuple[ExperienceItem, ...] = ()
        if request.context.get("requested_action") is True:
            suggestions = (
                ExperienceItem(
                    item_id="explore-action-handoff",
                    title="如需执行变化，请转入 Capture 或 Plan。",
                    reason_code="action_requires_capture_or_plan",
                    requires_confirmation=True,
                ),
            )
        uncertainties = ()
        status = "completed"
        if invalid_count:
            status = "partial"
            uncertainties = (
                ExperienceItem(
                    item_id="explore-invalid-evidence",
                    title="部分证据格式无效，已忽略。",
                    reason_code="invalid_evidence_data",
                ),
            )
        return ExperienceResponse(
            flow=FlowName.EXPLORE,
            status=status,
            understood=tuple(findings),
            suggestions=suggestions,
            uncertainties=uncertainties,
        )


def _items(result: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(result, Mapping):
        return ()
    value = result.get("items")
    if value is None:
        nodes = result.get("nodes")
        if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
            return ()
        return tuple(
            {
                "title": node.get("title"),
                "summary": node.get("content"),
                "source": node.get("id"),
                "observed_at": node.get("observed_at", "unspecified"),
                "confidence": node.get("confidence"),
            }
            for node in nodes
            if isinstance(node, Mapping)
        )
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _finding(
    item: Mapping[str, Any], index: int, time_range: Any
) -> ExperienceItem | None:
    title = item.get("title")
    summary = item.get("summary")
    source = item.get("source")
    observed_at = item.get("observed_at")
    confidence = item.get("confidence")
    if not all(isinstance(value, str) and value.strip() for value in (title, summary, source, observed_at)):
        return None
    if isinstance(time_range, str) and time_range.strip() and observed_at == "unspecified":
        return None
    if type(confidence) not in {int, float} or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        return None
    return ExperienceItem(
        item_id=f"explore-finding-{index}",
        title=title.strip(),
        reason_code="evidence_based_finding",
        after={
            "summary": summary.strip(),
            "evidence": source.strip(),
            "observed_at": observed_at.strip(),
            "time_range": time_range if isinstance(time_range, str) else "unspecified",
            "confidence": confidence,
        },
    )


def _safe_reason(value: Any) -> str:
    if isinstance(value, str) and _SAFE_REASON.fullmatch(value):
        return value
    return "source_unavailable"
