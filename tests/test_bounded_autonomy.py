from sre_agent.autonomy.lifecycle import (
    advance_iteration_node,
    initialize_lifecycle_node,
)



#######################################
# Unit-test - Инициализация lifecycle
#######################################
def test_initialize_lifecycle_from_goal():

    """
    Тестируем инициализцию lifecycle из объекта AgentGoal
    """

    # Создаем состояние
    state = {
        "goal": {
            "description": "Ensure payment-api has 3 ready replicas",
            "success_criteria": [
                "spec.replicas == 3",
                "status.readyReplicas == 3",
            ],
            "constraints": [
                "Do not modify unrelated resources",
            ],
            "max_iterations": 5,
        }
    }


    # Вызываем ноду
    result = initialize_lifecycle_node(state)

    assert result["iteration_count"] == 0

    assert result["max_iterations"] == 5

    assert result["termination_reason"] is None


#######################################
# Unit-test Conditional Edge - Счётчик
#######################################
def test_iteration_count_cannot_exceed_limit():
    """
    Тестируем счётчик не может превысить лимит.
    """

    state = {
        "iteration_count": 3,
        "max_iterations": 3,
        "termination_reason": None,
    }

    # Вызов ноды счётчика
    result = advance_iteration_node(state)

    assert result["iteration_count"] == 3

    assert result["termination_reason"] == "max_iterations_reached"


#######################################
# Unit-test Conditional Edge - Последния итерация
#######################################
def test_last_allowed_iteration_is_completed():

    """
    Тестируем выполнение последней разрешённой итерации.
    """

    state = {
        "iteration_count": 2,
        "max_iterations": 3,
        "termination_reason": None,
    }

    # Вызов ноды счётчика
    result = advance_iteration_node(state)

    assert result["iteration_count"] == 3

    assert "termination_reason" not in result
