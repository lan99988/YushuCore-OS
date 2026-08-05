from __future__ import annotations


def test_phase4_network_mode_off_blocks_external_calls_and_sync():
    from runtime_core.integration_policy import IntegrationPolicy

    policy = IntegrationPolicy(network_mode="OFF")

    assert policy.allows_local_runtime is True
    assert policy.allows_external_network is False
    assert policy.allows_background_sync is False


def test_phase4_network_mode_assist_requires_human_trigger_and_blocks_sync():
    from runtime_core.integration_policy import IntegrationPolicy

    policy = IntegrationPolicy(network_mode="ASSIST")

    assert policy.allows_human_triggered_external_query is True
    assert policy.allows_background_sync is False
    assert policy.route_external_data("pdf", "new note")["destination"] == "00_Inbox"


def test_phase4_network_mode_sync_routes_external_data_through_inbox_review():
    from runtime_core.integration_policy import IntegrationPolicy

    policy = IntegrationPolicy(network_mode="SYNC")

    routed = policy.route_external_data("web", "new note")

    assert routed["source"] == "web"
    assert routed["destination"] == "00_Inbox"
    assert routed["status"] == "review_required"
