import pytest

from sre_agent.tools.catalog import ToolCategory
from sre_agent.tools.registry import TOOL_REGISTRY


EXPECTED_READ_TOOLS = {
    "list_pods_tool",
    "get_pod_tool",
    "get_pod_logs_tool",
    "get_pod_events_tool",
    "list_nodes_tool",
    "get_node_tool",
    "get_node_events_tool",
    "get_deployment_tool",
}


def test_current_registry_contains_expected_tools():
    assert set(TOOL_REGISTRY) == EXPECTED_READ_TOOLS



@pytest.mark.parametrize("name", sorted(EXPECTED_READ_TOOLS),)
def test_current_tool_is_read_only(name):
    """
    Тестирование все Инструменты в TOOL_REGISTRY имеют категорию READ только.
    """
    # Получаем обьект Инструмент из реестра TOOL_REGISTRY
    definition = TOOL_REGISTRY[name]

    assert definition.category == ToolCategory.READ





@pytest.mark.parametrize("name", sorted(EXPECTED_READ_TOOLS))
def test_registry_key_matches_actual_tool_name(name):
    """
    Тестирование Ключ реестра совпадает с реальным именем toolи есть схема аргументов.
    """
    definition = TOOL_REGISTRY[name]

    assert definition.tool.name == name
 
    assert definition.tool.args_schema is not None