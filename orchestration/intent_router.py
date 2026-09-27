from __future__ import annotations

from collections.abc import Callable
import math
import re
from uuid import uuid4

from .contracts import ClarificationRequest, FlowName, UserIntent
from .errors import ClassificationError
from .flow_registry import FlowRegistry


Classifier = Callable[[str], tuple[FlowName, float, tuple[str, ...]]]

_HIGH_RISK_CUES = (
    "承诺",
    "答应",
    "付款",
    "支付",
    "转账",
    "发送",
    "发给",
    "删除",
    "移除",
    "销毁",
    "购买",
    "下单",
    "签署",
    "签字",
    "提交",
)
_HIGH_RISK_ENGLISH = re.compile(
    r"\b(?:commit|pay|payment|send|delete|transfer|purchase|sign)\b",
    flags=re.IGNORECASE,
)


class IntentRouter:
    """Route one user input to one primary flow, asking when confidence is low."""

    def __init__(
        self,
        *,
        classifier: Classifier | None = None,
        flow_registry: FlowRegistry | None = None,
        confidence_threshold: float = 0.7,
    ) -> None:
        if classifier is not None and not callable(classifier):
            raise TypeError("classifier must be callable")
        if (
            type(confidence_threshold) is not float
            or not math.isfinite(confidence_threshold)
            or not 0.0 <= confidence_threshold <= 1.0
        ):
            raise ValueError("confidence_threshold must be a finite float between 0 and 1")
        self.classifier = classifier
        self.flow_registry = flow_registry or FlowRegistry()
        self.confidence_threshold = confidence_threshold

    def route(
        self,
        text: str,
        *,
        correlation_id: str | None = None,
        structured_flow: FlowName | str | None = None,
    ) -> UserIntent | ClarificationRequest:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        request_id = correlation_id or uuid4().hex
        high_risk = self._is_high_risk(text)

        if structured_flow is not None:
            flow = self._parse_structured_flow(structured_flow)
            return UserIntent(
                flow=flow,
                text=text,
                confidence=1.0,
                evidence=("structured_input",),
                correlation_id=request_id,
            )

        match = self.flow_registry.match(text)
        if match is not None:
            flow, confidence, evidence = match.flow, match.confidence, match.evidence
        elif self.classifier is not None:
            flow, confidence, evidence = self._classify(text)
        else:
            reason_code = (
                "low_confidence_high_risk" if high_risk else "intent_not_recognized"
            )
            return self._clarification(
                text,
                request_id,
                reason_code=reason_code,
                confidence=0.0,
                high_risk=high_risk,
                candidate_flow=None,
            )

        if confidence < self.confidence_threshold:
            reason_code = (
                "low_confidence_high_risk" if high_risk else "low_confidence"
            )
            return self._clarification(
                text,
                request_id,
                reason_code=reason_code,
                confidence=confidence,
                high_risk=high_risk,
                candidate_flow=flow,
            )

        return UserIntent(
            flow=flow,
            text=text,
            confidence=confidence,
            evidence=evidence,
            correlation_id=request_id,
        )

    def _classify(self, text: str) -> tuple[FlowName, float, tuple[str, ...]]:
        try:
            result = self.classifier(text)
        except Exception as exc:
            raise ClassificationError("classifier failed") from exc
        if type(result) is not tuple or len(result) != 3:
            raise ClassificationError(
                "classifier must return (FlowName, confidence, evidence tuple)"
            )
        flow, confidence, evidence = result
        if not isinstance(flow, FlowName):
            raise ClassificationError("classifier flow must be a FlowName")
        if (
            type(confidence) is not float
            or not math.isfinite(confidence)
            or not 0.0 <= confidence <= 1.0
        ):
            raise ClassificationError("classifier confidence must be a float from 0 to 1")
        if type(evidence) is not tuple or any(
            not isinstance(item, str) or not item.strip() for item in evidence
        ):
            raise ClassificationError("classifier evidence must be a tuple of non-empty strings")
        return flow, confidence, evidence

    @staticmethod
    def _parse_structured_flow(flow: FlowName | str) -> FlowName:
        if isinstance(flow, FlowName):
            return flow
        if isinstance(flow, str):
            try:
                return FlowName(flow)
            except ValueError as exc:
                raise ValueError(f"unsupported structured flow: {flow}") from exc
        raise TypeError("structured_flow must be a FlowName or flow string")

    @staticmethod
    def _is_high_risk(text: str) -> bool:
        lowered = text.casefold()
        return any(cue in lowered for cue in _HIGH_RISK_CUES) or bool(
            _HIGH_RISK_ENGLISH.search(text)
        )

    @staticmethod
    def _clarification(
        text: str,
        correlation_id: str,
        *,
        reason_code: str,
        confidence: float,
        high_risk: bool,
        candidate_flow: FlowName | None,
    ) -> ClarificationRequest:
        if high_risk:
            question = (
                "这句话可能涉及承诺、付款、发送或删除等高风险动作。"
                "请先澄清希望走哪条主流程；确认前不会按该意图继续。"
            )
        else:
            question = (
                "我还不确定你希望走哪条主流程。请确认：记录、计划、今日、"
                "调整、回顾或探索？"
            )
        return ClarificationRequest(
            text=text,
            question=question,
            reason_code=reason_code,
            confidence=confidence,
            high_risk=high_risk,
            correlation_id=correlation_id,
            candidate_flow=candidate_flow,
        )
