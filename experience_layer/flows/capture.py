from __future__ import annotations

from collections.abc import Mapping
import hashlib
import re
from typing import Any

from orchestration import CapabilityRequest, FlowName, UserIntent

from experience_layer.contracts import (
    ExperienceItem,
    ExperienceRequest,
    ExperienceResponse,
)


_COMMITMENT_PATTERN = re.compile(
    r"(?:我)?答应(?P<deadline>.+?)前把(?P<object>.+?)发给"
    r"(?P<person>[^，。,.!！?？\s]+)"
)
_TASK_DEADLINE_PATTERN = re.compile(
    r"(?P<deadline>今天|明天|后天|本周[一二三四五六日天]|下周[一二三四五六日天]|"
    r"周[一二三四五六日天]|(?:\d{1,2}月)?\d{1,2}[日号])前"
    r"(?P<task>[^，。,.!！?？]+)"
)
_INTEREST_PATTERN = re.compile(
    r"对(?P<title>[^，。,.!！?？]{1,40}?)(?:很|非常|挺)?感兴趣"
)


class CaptureFlow:
    """Capture first, then propose any extracted commitment as a governed action."""

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
        if not isinstance(intent, UserIntent) or intent.flow is not FlowName.CAPTURE:
            raise ValueError("capture flow requires a Capture intent")

        commitment = _extract_commitment(request.text)
        captured_task = None if commitment is not None else _extract_task(request.text)
        domain_capture = _extract_domain_capture(request.text, request.context)
        understood = _understood_items(commitment, captured_task, domain_capture)
        requests = [
            CapabilityRequest(
                "capture-record",
                "information.capture",
                {
                    "source": "manual",
                    "title": request.text[:80],
                    "content": request.text,
                    "correlation_id": request.correlation_id,
                },
            )
        ]
        if commitment is not None:
            requests.append(
                CapabilityRequest(
                    "commitment-task",
                    "task.create_proposal",
                    {
                        "title": commitment["task"],
                        "evidence": [request.text],
                        "due_at": commitment["deadline"],
                        "affects_commitment": True,
                        "external_commitment": True,
                    },
                    depends_on=("capture-record",),
                )
            )
        elif captured_task is not None:
            requests.append(
                CapabilityRequest(
                    "captured-task",
                    "task.create_proposal",
                    {
                        "title": captured_task["task"],
                        "evidence": [request.text],
                        "due_at": captured_task["deadline"],
                        "affects_commitment": False,
                        "external_commitment": False,
                    },
                    depends_on=("capture-record",),
                )
            )
        if domain_capture is not None:
            requests.append(
                CapabilityRequest(
                    domain_capture["step_id"],
                    domain_capture["capability"],
                    domain_capture["payload"],
                    depends_on=("capture-record",),
                )
            )

        planning = self._planner.plan(
            intent,
            tuple(requests),
            assumptions=("用户输入按原文留存，结构化对象为可审阅解释。",),
        )
        if planning.plan is None or planning.gaps:
            uncertainties = tuple(
                ExperienceItem(
                    item_id=f"uncertainty-{index}",
                    title="所需能力暂不可用，请稍后重试。",
                    reason_code=gap.reason_code,
                )
                for index, gap in enumerate(planning.gaps, start=1)
            )
            return ExperienceResponse(
                flow=FlowName.CAPTURE,
                status="blocked",
                understood=understood,
                uncertainties=uncertainties,
                diagnostics=tuple(
                    {
                        "step_id": gap.step_id,
                        "capability": gap.capability,
                        "reason_code": gap.reason_code,
                    }
                    for gap in planning.gaps
                ),
            )

        execution = self._executor.execute(
            planning.plan,
            agent_id=self._agent_id,
            dry_run=request.dry_run,
        )
        recorded: list[ExperienceItem] = []
        suggestions: list[ExperienceItem] = []
        confirmations: list[ExperienceItem] = []
        uncertainties: list[ExperienceItem] = []
        diagnostics: list[dict[str, Any]] = []
        request_by_step = {item.step_id: item for item in requests}

        for step in execution.steps:
            capability = request_by_step[step.step_id].capability
            reason_code = _step_reason(step)
            diagnostics.append(
                {
                    "step_id": step.step_id,
                    "capability": capability,
                    "status": step.status,
                    "reason_code": reason_code,
                }
            )
            if step.step_id == "capture-record":
                if step.status == "completed":
                    recorded.append(
                        ExperienceItem(
                            item_id="recorded-information",
                            title="已记录原始信息。",
                            reason_code="information_recorded",
                        )
                    )
                elif step.status == "planned":
                    suggestions.append(
                        ExperienceItem(
                            item_id="preview-information",
                            title="准备记录这条信息。",
                            reason_code="information_capture_preview",
                        )
                    )
                else:
                    uncertainties.append(
                        ExperienceItem(
                            item_id="uncertainty-information",
                            title="原始信息尚未记录，请稍后重试。",
                            reason_code=reason_code,
                        )
                    )
                continue

            if domain_capture is not None and step.step_id == domain_capture["step_id"]:
                _append_domain_result(
                    step,
                    domain_capture,
                    recorded=recorded,
                    suggestions=suggestions,
                    confirmations=confirmations,
                    uncertainties=uncertainties,
                )
                continue

            task_details = commitment or captured_task
            task_label = "承诺任务" if commitment is not None else "任务"
            if step.status == "blocked" and getattr(
                step.decision, "approval_required", False
            ):
                confirmations.append(
                    ExperienceItem(
                        item_id=f"confirmation-{step.step_id}",
                        title=f"请确认{task_label}：{task_details['task']}",
                        reason_code=reason_code,
                        requires_confirmation=True,
                    )
                )
            elif step.status == "planned":
                suggestions.append(
                    ExperienceItem(
                        item_id=f"preview-{step.step_id}",
                        title=f"准备生成{task_label}：{task_details['task']}",
                        reason_code=(
                            "commitment_task_preview"
                            if commitment is not None
                            else "task_preview"
                        ),
                    )
                )
            elif step.status == "completed":
                recorded.append(
                    ExperienceItem(
                        item_id=f"recorded-{step.step_id}",
                        title=f"已生成{task_label}提案：{task_details['task']}",
                        reason_code=(
                            "commitment_task_proposed"
                            if commitment is not None
                            else "task_proposed"
                        ),
                    )
                )
            else:
                uncertainties.append(
                    ExperienceItem(
                        item_id="uncertainty-commitment",
                        title="承诺任务尚未生成。",
                        reason_code=reason_code,
                    )
                )

        return ExperienceResponse(
            flow=FlowName.CAPTURE,
            status=_experience_status(execution.status),
            understood=understood,
            recorded=tuple(recorded),
            suggestions=tuple(suggestions),
            confirmations=tuple(confirmations),
            uncertainties=tuple(uncertainties),
            diagnostics=tuple(diagnostics),
        )


def _extract_commitment(text: str) -> dict[str, str] | None:
    match = _COMMITMENT_PATTERN.search(text)
    if match is None:
        return None
    deadline = match.group("deadline").strip()
    object_name = match.group("object").strip()
    person = match.group("person").strip()
    return {
        "deadline": deadline,
        "object": object_name,
        "person": person,
        "commitment": f"{deadline}前把{object_name}发给{person}",
        "task": f"把{object_name}发给{person}",
    }


def _extract_task(text: str) -> dict[str, str] | None:
    match = _TASK_DEADLINE_PATTERN.search(text)
    if match is None:
        return None
    deadline = match.group("deadline").strip()
    task = match.group("task").strip()
    if not task:
        return None
    return {"deadline": deadline, "task": task}


def _extract_domain_capture(
    text: str, context: Mapping[str, Any]
) -> dict[str, Any] | None:
    if "护照" in text and any(
        marker in text for marker in ("到期", "过期", "有效期", "续期", "换发")
    ):
        payload: dict[str, Any] = {"text": text}
        reference_date = context.get("reference_date")
        if isinstance(reference_date, str) and reference_date.strip():
            payload["reference_date"] = reference_date.strip()
        return {
            "kind": "life_admin",
            "step_id": "capture-life-admin",
            "capability": "life_admin.capture",
            "payload": payload,
            "title": "护照到期事项",
        }
    match = _INTEREST_PATTERN.search(text)
    if match is None:
        return None
    title = match.group("title").strip()
    if not title:
        return None
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
    return {
        "kind": "interest",
        "step_id": "capture-interest",
        "capability": "interest.record_proposal",
        "payload": {"interest_id": f"interest:{digest}", "title": title},
        "title": title,
    }


def _understood_items(
    commitment: dict[str, str] | None,
    captured_task: dict[str, str] | None = None,
    domain_capture: dict[str, Any] | None = None,
) -> tuple[ExperienceItem, ...]:
    domain_items: tuple[ExperienceItem, ...] = ()
    if domain_capture is not None:
        if domain_capture["kind"] == "life_admin":
            domain_items = (
                ExperienceItem(
                    item_id="understood-life-admin",
                    title="识别到生活行政事项：护照到期。",
                    reason_code="life_admin_recognized",
                ),
            )
        else:
            domain_items = (
                ExperienceItem(
                    item_id="understood-interest",
                    title=f"识别到兴趣主题：{domain_capture['title']}",
                    reason_code="interest_recognized",
                ),
            )
    if commitment is None and captured_task is None:
        if domain_items:
            return domain_items
        return (
            ExperienceItem(
                item_id="understood-information",
                title="识别到一条新信息。",
                reason_code="information_recognized",
            ),
        )
    if captured_task is not None:
        return (
            ExperienceItem(
                item_id="understood-task",
                title=f"识别到任务：{captured_task['task']}（{captured_task['deadline']}前）",
                reason_code="task_recognized",
            ),
        ) + domain_items
    return (
        ExperienceItem(
            item_id="understood-person",
            title=f"识别到联系人：{commitment['person']}",
            reason_code="person_recognized",
        ),
        ExperienceItem(
            item_id="understood-commitment",
            title=f"识别到承诺：{commitment['commitment']}",
            reason_code="commitment_recognized",
        ),
        ExperienceItem(
            item_id="understood-task",
            title=f"识别到任务：{commitment['task']}",
            reason_code="task_recognized",
        ),
    ) + domain_items


def _append_domain_result(
    step: Any,
    domain_capture: dict[str, Any],
    *,
    recorded: list[ExperienceItem],
    suggestions: list[ExperienceItem],
    confirmations: list[ExperienceItem],
    uncertainties: list[ExperienceItem],
) -> None:
    reason_code = _step_reason(step)
    kind = domain_capture["kind"]
    if step.status == "planned":
        suggestions.append(
            ExperienceItem(
                item_id=f"preview-{step.step_id}",
                title=(
                    "准备识别生活行政事项并生成待审提醒。"
                    if kind == "life_admin"
                    else f"准备记录兴趣主题：{domain_capture['title']}"
                ),
                reason_code=f"{kind}_capture_preview",
            )
        )
        return
    if step.status != "completed" or not isinstance(step.result, Mapping):
        uncertainties.append(
            ExperienceItem(
                item_id=f"uncertainty-{step.step_id}",
                title="领域事项尚未生成提案。",
                reason_code=reason_code,
            )
        )
        return
    result = step.result
    if result.get("needs_clarification") is True:
        clarification = result.get("reason_code")
        uncertainties.append(
            ExperienceItem(
                item_id="uncertainty-life-admin-date",
                title="需要明确护照到期年份后才能生成提醒。",
                reason_code=(
                    clarification
                    if isinstance(clarification, str) and clarification
                    else "life_admin_date_required"
                ),
            )
        )
        return
    if kind == "life_admin":
        proposals = result.get("proposals")
        proposal = (
            proposals[0]
            if isinstance(proposals, list)
            and proposals
            and isinstance(proposals[0], Mapping)
            else None
        )
        if proposal is None:
            recorded.append(
                ExperienceItem(
                    item_id="recorded-life-admin",
                    title="已识别生活行政事项。",
                    reason_code="life_admin_captured",
                )
            )
            return
        confirmations.append(
            ExperienceItem(
                item_id="confirmation-life-admin-reminder",
                title=str(proposal.get("title") or "请确认生活行政提醒。"),
                reason_code="life_admin_reminder_review",
                after={
                    "activated_subdomain": result.get("activated_subdomain"),
                    "due_at": proposal.get("due_at"),
                    "executed": proposal.get("executed") is True,
                    "proposal_type": proposal.get("proposal_type"),
                },
                requires_confirmation=True,
            )
        )
        return
    topic = result.get("topic")
    if not isinstance(topic, Mapping):
        uncertainties.append(
            ExperienceItem(
                item_id="uncertainty-interest-result",
                title="兴趣主题提案格式无效。",
                reason_code="invalid_interest_proposal",
            )
        )
        return
    confirmations.append(
        ExperienceItem(
            item_id="confirmation-interest-topic",
            title=f"请确认兴趣主题：{topic.get('title')}",
            reason_code="interest_topic_review",
            after={
                "proposal_type": result.get("proposal_type"),
                "interest_id": topic.get("interest_id"),
                "title": topic.get("title"),
                "executed": result.get("executed") is True,
            },
            requires_confirmation=True,
        )
    )


def _step_reason(step: Any) -> str:
    decision = getattr(step, "decision", None)
    reason = getattr(decision, "reason_code", None) or getattr(
        step, "error_code", None
    )
    return reason if isinstance(reason, str) and reason else "step_not_completed"


def _experience_status(status: str) -> str:
    if status in {"completed", "partial"}:
        return status
    if status == "dry_run":
        return "completed"
    return "blocked"
