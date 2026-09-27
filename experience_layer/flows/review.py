from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from orchestration import CapabilityRequest, FlowName, UserIntent

from experience_layer.contracts import (
    ExperienceItem,
    ExperienceRequest,
    ExperienceResponse,
    thaw_snapshot,
)


_READS = (
    ("review-project", "project.context"),
    ("review-learning", "learning.progress"),
)
_CATEGORIES = (
    ("behaviors", "behavior_observed", "行为"),
    ("results", "result_observed", "结果"),
    ("trends", "trend_observed", "趋势"),
    ("problems", "problem_identified", "问题"),
    ("cause_hypotheses", "cause_hypothesis", "原因假设"),
)
_SAFE_REASON = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class ReviewFlow:
    """Turn governed read results into an evidence-bounded review chain."""

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
        if not isinstance(intent, UserIntent) or intent.flow is not FlowName.REVIEW:
            raise ValueError("review flow requires a Review intent")

        finance_payload = _finance_review_payload(request.context)
        period = request.context.get("period")
        payload = {"period": thaw_snapshot(period)} if period is not None else {}
        project_id = request.context.get("project_id")
        if isinstance(project_id, str) and project_id.strip():
            payload["project_id"] = project_id.strip()
        source_specs = (
            (("review-finance", "finance.monthly_snapshot"),)
            if finance_payload is not None
            else _READS
        )
        capability_requests = tuple(
            CapabilityRequest(
                step_id,
                capability,
                finance_payload if step_id == "review-finance" else payload,
            )
            for step_id, capability in source_specs
        )
        planning = self._planner.plan(
            intent,
            capability_requests,
            assumptions=(
                (
                    "只生成月度财务聚合快照提案，不读取逐笔流水。"
                    if finance_payload is not None
                    else "只读取项目和学习结果，不修改来源数据。"
                ),
                "因果关系仅作为有证据数量的假设呈现。",
            ),
        )
        if planning.plan is None or planning.gaps:
            gaps = tuple(planning.gaps)
            uncertainties = tuple(
                ExperienceItem(
                    item_id=f"review-plan-gap-{index}",
                    title="复盘所需的数据暂不可用。",
                    reason_code=_safe_reason(gap.reason_code),
                )
                for index, gap in enumerate(gaps, start=1)
            ) or (
                ExperienceItem(
                    item_id="review-plan-unavailable",
                    title="暂时无法生成复盘。",
                    reason_code="planning_unavailable",
                ),
            )
            return ExperienceResponse(
                flow=FlowName.REVIEW,
                status="blocked",
                uncertainties=uncertainties,
            )

        execution = self._executor.execute(
            planning.plan,
            agent_id=self._agent_id,
            dry_run=request.dry_run,
        )
        results = {step.step_id: step for step in execution.steps}
        sources: list[tuple[str, Mapping[str, Any]]] = []
        uncertainties: list[ExperienceItem] = []
        diagnostics: list[dict[str, Any]] = []
        for step_id, capability in source_specs:
            step = results.get(step_id)
            if step is None or step.status != "completed":
                reason = _safe_reason(
                    getattr(step, "error_code", None)
                    or getattr(step, "status", None)
                    or "step_result_missing"
                )
                uncertainties.append(
                    ExperienceItem(
                        item_id=f"review-source-{step_id}",
                        title="一项复盘数据源暂不可用。",
                        reason_code=reason,
                    )
                )
                diagnostics.append(
                    {"step_id": step_id, "capability": capability, "status": "unavailable"}
                )
                continue
            if not isinstance(step.result, Mapping):
                uncertainties.append(
                    ExperienceItem(
                        item_id=f"review-invalid-{step_id}",
                        title="一项复盘数据格式无效。",
                        reason_code="invalid_review_data",
                    )
                )
                continue
            source_data = step.result.get("context", step.result)
            if not isinstance(source_data, Mapping):
                uncertainties.append(
                    ExperienceItem(
                        item_id=f"review-invalid-context-{step_id}",
                        title="一项复盘上下文格式无效。",
                        reason_code="invalid_review_data",
                    )
                )
                continue
            normalized_source = _normalize_source(step_id, source_data)
            if normalized_source is None:
                uncertainties.append(
                    ExperienceItem(
                        item_id=f"review-unknown-shape-{step_id}",
                        title="一项复盘数据不符合受支持的结构，已忽略。",
                        reason_code="invalid_review_data",
                    )
                )
                continue
            sources.append((step_id, normalized_source))

        understood: list[ExperienceItem] = []
        for field, reason_code, label in _CATEGORIES:
            for source_index, (source_id, data) in enumerate(sources, start=1):
                for item_index, item in enumerate(_records(data.get(field)), start=1):
                    title = _title(item)
                    if not title:
                        continue
                    after = None
                    display_title = f"{label}：{title}"
                    if field == "cause_hypotheses":
                        evidence = item.get("evidence", ())
                        evidence_count = (
                            len(evidence)
                            if isinstance(evidence, Sequence)
                            and not isinstance(evidence, (str, bytes))
                            else 0
                        )
                        after = {"evidence_count": evidence_count}
                    elif isinstance(item.get("snapshot"), Mapping):
                        after = dict(item["snapshot"])
                    understood.append(
                        ExperienceItem(
                            item_id=f"review-{field}-{source_index}-{item_index}",
                            title=display_title,
                            reason_code=reason_code,
                            after=after,
                        )
                    )

        suggestions: list[ExperienceItem] = []
        for source_index, (_, data) in enumerate(sources, start=1):
            for item_index, item in enumerate(_records(data.get("recommendations")), start=1):
                title = _title(item)
                if title:
                    suggestions.append(
                        ExperienceItem(
                            item_id=f"review-recommendation-{source_index}-{item_index}",
                            title=f"建议：{title}",
                            reason_code="review_recommendation",
                        )
                    )
            next_cycle = data.get("next_cycle")
            if isinstance(next_cycle, Mapping):
                suggestions.append(
                    ExperienceItem(
                        item_id=f"review-next-cycle-{source_index}",
                        title="将本轮结论作为下一周期计划输入。",
                        reason_code="next_cycle_input",
                        after=dict(next_cycle),
                    )
                )
            if _records(data.get("causes")):
                uncertainties.append(
                    ExperienceItem(
                        item_id=f"review-unsupported-cause-{source_index}",
                        title="数据源包含未经证据支持的确定性因果结论，已忽略。",
                        reason_code="unsupported_causal_claim",
                    )
                )

        if not sources:
            status = "blocked"
        elif not understood and not suggestions:
            uncertainties.append(
                ExperienceItem(
                    item_id="review-insufficient-evidence",
                    title="当前周期没有足够的行为或结果证据可供复盘。",
                    reason_code="insufficient_review_evidence",
                )
            )
            status = "needs_clarification"
        elif uncertainties or execution.status != "completed":
            status = "partial"
        else:
            status = "completed"
        return ExperienceResponse(
            flow=FlowName.REVIEW,
            status=status,
            understood=tuple(understood),
            suggestions=tuple(suggestions),
            uncertainties=tuple(uncertainties),
            diagnostics=tuple(diagnostics),
        )


def _records(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _title(item: Mapping[str, Any]) -> str:
    value = item.get("title")
    return value.strip() if isinstance(value, str) else ""


def _normalize_source(
    step_id: str, data: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    if step_id == "review-finance":
        return _normalize_finance_source(data)
    supported = {field for field, _, _ in _CATEGORIES} | {
        "recommendations",
        "next_cycle",
        "causes",
    }
    if step_id == "review-learning" and {"completed", "target"} <= set(data):
        completed = data.get("completed")
        target = data.get("target")
        if (
            type(completed) not in {int, float}
            or type(target) not in {int, float}
            or completed < 0
            or target <= 0
        ):
            return None
        copied = dict(data)
        existing = list(_records(copied.get("results")))
        existing.append(
            {
                "title": f"学习进度 {completed}/{target}",
                "snapshot": {
                    "completed": completed,
                    "target": target,
                    "ratio": completed / target,
                },
            }
        )
        copied["results"] = existing
        return copied
    if not data or set(data) & supported:
        return data
    return None


def _finance_review_payload(context: Mapping[str, Any]) -> dict[str, Any] | None:
    month = context.get("finance_month")
    image_refs = context.get("finance_image_refs")
    if month is None and image_refs is None:
        return None
    if not isinstance(month, str) or not month.strip():
        return None
    refs = thaw_snapshot(image_refs)
    if (
        type(refs) is not list
        or not refs
        or any(not isinstance(ref, str) or not ref.strip() for ref in refs)
    ):
        return None
    return {"month": month.strip(), "image_refs": refs}


def _normalize_finance_source(data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    snapshot = data.get("snapshot")
    if not isinstance(snapshot, Mapping):
        return None
    required = (
        "month",
        "total_income",
        "total_expenses",
        "balance",
        "savings_rate",
    )
    if any(field not in snapshot for field in required):
        return None
    summary = {field: thaw_snapshot(snapshot[field]) for field in required}
    normalized: dict[str, Any] = {
        "results": [
            {
                "title": f"{summary['month']} 财务快照",
                "snapshot": summary,
            }
        ],
        "trends": [],
        "problems": [],
        "recommendations": [],
    }
    analysis = snapshot.get("ai_analysis")
    if isinstance(analysis, str) and analysis.strip():
        normalized["trends"].append({"title": analysis.strip()})
    anomalies = snapshot.get("anomalies")
    if isinstance(anomalies, Sequence) and not isinstance(anomalies, (str, bytes)):
        normalized["problems"] = [
            {"title": item.strip()}
            for item in anomalies
            if isinstance(item, str) and item.strip()
        ]
    focus = snapshot.get("next_month_focus")
    if isinstance(focus, Sequence) and not isinstance(focus, (str, bytes)):
        normalized["recommendations"] = [
            {"title": item.strip()}
            for item in focus
            if isinstance(item, str) and item.strip()
        ]
    return normalized


def _safe_reason(value: Any) -> str:
    if isinstance(value, str) and _SAFE_REASON.fullmatch(value):
        return value
    return "source_unavailable"
