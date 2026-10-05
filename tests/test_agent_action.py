import pytest

from pydantic import ValidationError

from sre_agent.state import AgentAction

#######################################
#  Подготовка к тестированию
#######################################
@pytest.fixture
def action_payload():
    return {
        "action_id": "read-pod-status",
        "tool": "get_pod_tool",
        "arguments": {
            "cluster_alias": "test-cluster",
            "namespace": "payments",
            "pod_name": "payment-api-1",
        },
        "expected_result": "Obtain current pod status.",
        "risk_level": "read",
    }


#######################################
# Unit-test - Тестирование сериализации и восстановления 
#######################################
def test_action_can_be_serialized(action_payload):
    """
    Тестирование сериализации и восстановления 
    """
    # Валидация при создании объекта 
    action = AgentAction.model_validate(action_payload)

    # Валидация и создание объекта
    restored = AgentAction.model_validate_json(
        action.model_dump_json()
    )
    assert  action == restored



#######################################
# Unit-test - Тестирование не поддерживаемого значения risk_level
#######################################
@pytest.mark.parametrize(
    "risk_level",
    ["critical", "write", "", None],
)
def test_action_rejects_unknown_risk(action_payload, risk_level):
    """
    Тестирование не поддерживаемого значения risk_level
    """
    # Перезаписываем parametrize значением  
    action_payload["risk_level"] = risk_level

    with pytest.raises(ValidationError):
        AgentAction.model_validate(action_payload)


#######################################
# Unit-test - Тестирование не поддерживаемого значения expected_result
#######################################
@pytest.mark.parametrize(
    "expected_result",
    ["", "  ", None],
)
def test_action_requires_expected_result(
    action_payload,
    expected_result,
):
    """
    Тестирование не поддерживаемого значения expected_result
    В классе AgentAction конфигурация model_config.str_strip_whitespace - убирает пробелы по краям строк
    """
    
    # Перезаписываем parametrize значением  
    action_payload["expected_result"] = expected_result

    with pytest.raises(ValidationError):
        AgentAction.model_validate(action_payload)


def test_action_rejects_unknown_fields(action_payload):
    """
    Тестирование не поддерживаемого значения expected_result
    В классе AgentAction конфигурация model_config.extra="forbid" отклоняет неизвестные поля    
    """

    # Записываем значение
    action_payload["command"] = "kubectl delete pod"

    with pytest.raises(ValidationError):
        AgentAction.model_validate(action_payload)