from __future__ import annotations

from dataclasses import dataclass
import math

from .contracts import FlowName


@dataclass(frozen=True)
class FlowRule:
    flow: FlowName
    cues: tuple[str, ...]
    confidence: float
    priority: int

    def __post_init__(self) -> None:
        if not isinstance(self.flow, FlowName):
            raise TypeError("flow must be a FlowName")
        if type(self.cues) is not tuple or not self.cues:
            raise TypeError("cues must be a non-empty tuple of strings")
        if any(not isinstance(cue, str) or not cue.strip() for cue in self.cues):
            raise ValueError("cues must contain non-empty strings")
        if type(self.confidence) is not float or not math.isfinite(self.confidence):
            raise ValueError("confidence must be a finite float")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if type(self.priority) is not int:
            raise TypeError("priority must be an integer")


@dataclass(frozen=True)
class FlowMatch:
    flow: FlowName
    confidence: float
    evidence: tuple[str, ...]


_DEFAULT_RULES = (
    FlowRule(
        FlowName.CAPTURE,
        (
            "记下",
            "记一下",
            "记录",
            "录入",
            "新增",
            "收集",
            "保存",
            "我答应",
            "我承诺",
            "前交",
            "护照",
            "capture",
            "note ",
            "save ",
        ),
        0.98,
        60,
    ),
    FlowRule(
        FlowName.PLAN,
        ("规划", "计划", "制定", "安排", "个月完成", "plan", "schedule"),
        0.94,
        50,
    ),
    FlowRule(
        FlowName.TODAY,
        (
            "今天有什么",
            "今日有什么",
            "今天待办",
            "今日待办",
            "今天的待办",
            "今日安排",
            "今天安排",
            "today",
            "daily agenda",
        ),
        0.96,
        55,
    ),
    FlowRule(
        FlowName.ADJUST,
        (
            "调整",
            "修改",
            "改期",
            "更改",
            "重排",
            "昨晚只睡",
            "睡眠不足",
            "adjust",
            "reschedule",
        ),
        0.96,
        80,
    ),
    FlowRule(
        FlowName.REVIEW,
        ("回顾", "复盘", "总结", "复查", "review", "retro"),
        0.97,
        70,
    ),
    FlowRule(
        FlowName.EXPLORE,
        (
            "探索",
            "研究",
            "了解",
            "解释",
            "查询",
            "查一下",
            "为什么",
            "如何",
            "what is",
            "explore",
            "research",
        ),
        0.92,
        40,
    ),
)


class FlowRegistry:
    """Deterministic registry of the six supported intent flows."""

    def __init__(self, rules: tuple[FlowRule, ...] = _DEFAULT_RULES) -> None:
        if type(rules) is not tuple or any(not isinstance(rule, FlowRule) for rule in rules):
            raise TypeError("rules must be a tuple of FlowRule values")
        registered = [rule.flow for rule in rules]
        if len(registered) != len(set(registered)):
            raise ValueError("flow rules must be unique")
        if set(registered) != set(FlowName):
            raise ValueError("flow registry must define all six FlowName values")
        self._rules = rules

    @property
    def flows(self) -> tuple[FlowName, ...]:
        return tuple(sorted((rule.flow for rule in self._rules), key=lambda flow: flow.value))

    def match(self, text: str) -> FlowMatch | None:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        normalized = text.casefold()
        matches: list[tuple[FlowRule, tuple[str, ...]]] = []
        for rule in self._rules:
            matched_cues = tuple(
                cue for cue in rule.cues if cue.casefold() in normalized
            )
            if matched_cues:
                matches.append((rule, matched_cues))
        if not matches:
            return None
        rule, evidence = max(
            matches,
            key=lambda match: (
                match[0].confidence,
                match[0].priority,
                len(match[1]),
                match[0].flow.value,
            ),
        )
        return FlowMatch(flow=rule.flow, confidence=rule.confidence, evidence=evidence)
