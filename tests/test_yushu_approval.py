from pathlib import Path

from yushu_app.application import YushuApplication
from yushu_app.profile import Profile


def _app(tmp_path: Path) -> YushuApplication:
    return YushuApplication(Profile.initialize("test", home=tmp_path))


def test_commitment_write_requires_persistent_owner_approval(tmp_path: Path):
    app = _app(tmp_path)
    pending = app.invoke_capability(
        "local_record.create",
        {"kind": "commitment", "data": {"title": "给朋友发资料"}, "affects_commitment": True},
        agent_id="agent-a", correlation_id="corr-commitment",
    )
    assert pending["status"] == "pending_approval"
    assert pending["approval_id"]
    assert app.store.list("commitment") == []
    review_item = app.approvals.list_pending()[0]
    assert review_item["approval_id"] == pending["approval_id"]
    assert review_item["payload"]["data"]["title"] == "给朋友发资料"
    assert len(review_item["payload_digest"]) == 64

    reopened = YushuApplication(Profile.open("test", home=tmp_path))
    denied = reopened.approve(pending["approval_id"], reviewer="agent-a")
    assert denied["status"] == "blocked"
    approved = reopened.approve(pending["approval_id"], reviewer="owner")
    assert approved["status"] == "completed"
    assert len(reopened.store.list("commitment")) == 1
    again = reopened.approve(pending["approval_id"], reviewer="owner")
    assert again["status"] == "blocked"


def test_agent_cannot_bypass_commitment_approval_by_omitting_risk_flag(tmp_path: Path):
    app = _app(tmp_path)
    result = app.invoke_capability(
        "local_record.create", {"kind": "commitment", "data": {"title": "答应发送资料"}},
        agent_id="agent-a", correlation_id="corr-omit-flag",
    )
    assert result["status"] == "pending_approval"
    assert app.store.list("commitment") == []
