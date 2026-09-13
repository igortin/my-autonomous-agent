from sre_agent.config import build_run_config

#######################################################
#  Тестируем функции build_run_config() 
#######################################################

def test_build_run_config_contains_observability_metadata():
    config = build_run_config(
        user_id="test-user",
        thread_id="thread-123",
        environment="test",
    )

    assert config["configurable"]["user_id"] == "test-user"
    assert config["configurable"]["thread_id"] == "thread-123"

    assert config["metadata"]["user_id"] == "test-user"
    assert config["metadata"]["environment"] == "test"
    assert config["metadata"]["agent"] == "sre_agent"

    assert "sre-agent" in config["tags"]
    assert "test" in config["tags"]