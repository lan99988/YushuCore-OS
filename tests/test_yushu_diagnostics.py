from datetime import datetime, timedelta, timezone

from yushu_app.diagnostics import ConnectorDiagnostics
from integrations.ollama import OllamaClient
import pytest


def test_read_only_diagnostics_classify_online_auth_timeout_and_missing():
    calls = []

    def online():
        calls.append("ima")
        return {"observed_at": datetime.now(timezone.utc).isoformat()}

    def unauthorized():
        raise RuntimeError("HTTP 401 secret response")

    def timeout():
        raise TimeoutError("private timeout body")

    diagnostics = ConnectorDiagnostics({"ima": online, "feishu": unauthorized,
                                        "garmin": timeout, "ollama": None})
    result = diagnostics.run(live=True)
    assert result["ima"]["status"] == "online"
    assert result["feishu"]["status"] == "auth_required"
    assert result["garmin"]["status"] == "timeout"
    assert result["ollama"]["status"] == "not_configured"
    assert "secret response" not in str(result)
    assert calls == ["ima"]


def test_diagnostics_reports_stale_data_and_never_probes_by_default():
    calls = []

    def stale():
        calls.append(1)
        return {"observed_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()}

    diagnostics = ConnectorDiagnostics({"garmin": stale})
    assert diagnostics.run()["garmin"]["status"] == "configured_unverified"
    assert calls == []
    assert diagnostics.run(live=True)["garmin"]["stale"] is True


def test_ollama_non_success_http_must_not_be_reported_available():
    class Response:
        status = 503

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    client = OllamaClient(opener=lambda request, timeout: Response())
    with pytest.raises(RuntimeError):
        client.health()
