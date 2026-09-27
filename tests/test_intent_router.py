import pytest

from orchestration.contracts import ClarificationRequest, FlowName, UserIntent
from orchestration.errors import ClassificationError
from orchestration.flow_registry import FlowRegistry
from orchestration.intent_router import IntentRouter


@pytest.mark.parametrize(
    ("text", "expected_flow"),
    [
        ("帮我记录今天的训练感受", FlowName.CAPTURE),
        ("规划本周的项目安排", FlowName.PLAN),
        ("今天有什么待办", FlowName.TODAY),
        ("把会议改期到周五", FlowName.ADJUST),
        ("复盘本周的任务", FlowName.REVIEW),
        ("研究怎样改善睡眠", FlowName.EXPLORE),
    ],
)
def test_router_maps_all_six_flows_without_a_classifier(text, expected_flow):
    result = IntentRouter().route(text, correlation_id="corr-1")

    assert isinstance(result, UserIntent)
    assert result.flow is expected_flow
    assert result.text == text
    assert result.confidence >= 0.7


def test_flow_registry_contains_exactly_the_six_supported_flows():
    assert set(FlowRegistry().flows) == set(FlowName)


def test_structured_flow_takes_precedence_and_does_not_call_classifier():
    calls = []

    def classifier(text):
        calls.append(text)
        return FlowName.EXPLORE, 0.99, ("backend",)

    result = IntentRouter(classifier=classifier).route(
        "一个没有规则关键词的输入",
        structured_flow=FlowName.CAPTURE,
        correlation_id="corr-structured",
    )

    assert result.flow is FlowName.CAPTURE
    assert "structured_input" in result.evidence
    assert calls == []


def test_injected_classifier_handles_unmatched_input_without_network():
    calls = []

    def classifier(text):
        calls.append(text)
        return FlowName.EXPLORE, 0.91, ("local classifier result",)

    result = IntentRouter(classifier=classifier).route(
        "帮我处理一下这个",
        correlation_id="corr-classifier",
    )

    assert isinstance(result, UserIntent)
    assert result.flow is FlowName.EXPLORE
    assert result.evidence == ("local classifier result",)
    assert calls == ["帮我处理一下这个"]


def test_unknown_input_without_classifier_returns_explicit_clarification():
    result = IntentRouter().route(
        "这件事接下来怎么处理",
        correlation_id="corr-unknown",
    )

    assert isinstance(result, ClarificationRequest)
    assert result.reason_code == "intent_not_recognized"
    assert result.question


def test_explicit_personal_commitment_routes_to_capture_without_module_selection():
    result = IntentRouter().route(
        "我答应周五前把资料发给李明",
        correlation_id="corr-capture-commitment",
    )

    assert isinstance(result, UserIntent)
    assert result.flow is FlowName.CAPTURE
    assert any("答应" in item for item in result.evidence)


def test_low_confidence_high_risk_input_requires_clarification():
    def classifier(text):
        return FlowName.PLAN, 0.42, ("weak match",)

    result = IntentRouter(classifier=classifier).route(
        "请答应周五前把资料发给李明",
        correlation_id="corr-risk",
    )

    assert isinstance(result, ClarificationRequest)
    assert result.high_risk is True
    assert result.candidate_flow is FlowName.PLAN
    assert result.reason_code == "low_confidence_high_risk"
    assert "澄清" in result.question


def test_low_confidence_input_is_not_silently_guessed():
    result = IntentRouter(
        classifier=lambda text: (FlowName.CAPTURE, 0.3, ("weak match",))
    ).route("大概处理一下这个", correlation_id="corr-low")

    assert isinstance(result, ClarificationRequest)
    assert result.reason_code == "low_confidence"
    assert result.candidate_flow is FlowName.CAPTURE


def test_one_input_selects_only_one_primary_flow():
    result = IntentRouter().route(
        "记录这个并顺便规划本周项目",
        correlation_id="corr-one-flow",
    )

    assert isinstance(result, UserIntent)
    assert result.flow is FlowName.CAPTURE
    assert not isinstance(result.flow, tuple)


def test_invalid_classifier_result_fails_closed():
    router = IntentRouter(classifier=lambda text: ("plan", 0.9, ("guess",)))

    with pytest.raises(ClassificationError):
        router.route("没有规则关键词", correlation_id="corr-invalid")
