def test_runtime_integrations_do_not_export_legacy_knowledge_sources():
    import integrations

    assert "LlmWikiAdapter" not in integrations.__all__
    assert "LlmWikiApiClient" not in integrations.__all__
    assert "ObsidianAdapter" not in integrations.__all__
    assert "KnowledgeMcpServer" not in integrations.__all__
