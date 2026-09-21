from sre_agent.autonomy.lifecycle import (
    advance_iteration_node,
    initialize_lifecycle_node,
    route_autonomous_lifecycle,
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
# Unit-test Conditional Edge - Продолжение lifecycle
#######################################
def test_lifecycle_continues_when_goal_not_reached():
    """
    Тестируем route continue.
    """

    state = {
        "iteration_count": 1,
        "max_iterations": 5,
        "termination_reason": None,
        "human_escalation_required": False,
        "rca_quality_check": {
            "needs_more_data": True,
        },
    }

    # Вызываем Conditional Edge
    route = route_autonomous_lifecycle(state)

    assert route == "continue"


#######################################
# Unit-test Conditional Edge - Goal reached
#######################################
def test_lifecycle_stops_when_goal_reached():
    """
    Тестируем route goal_reached.
    """
    state = {
        "iteration_count": 1,
        "max_iterations": 5,
        "termination_reason": None,
        "human_escalation_required": False,
        "rca_quality_check": {
            "needs_more_data": False,
        },
    }

    # Вызываем Conditional Edge
    route = route_autonomous_lifecycle(state)

    assert route == "goal_reached"


#######################################
# Unit-test Conditional Edge - Достижение лимита
#######################################
def test_lifecycle_stops_at_max_iterations():

    """
    Тестируем route max_iterations_reached.
    """

    state = {
        "iteration_count": 5,
        "max_iterations": 5,
        "termination_reason": None,
        "human_escalation_required": False,
        "rca_quality_check": {
            "needs_more_data": True,
        },
    }

    # Вызываем Conditional Edge
    route = route_autonomous_lifecycle(state)
    
    assert route == "max_iterations_reached"


#######################################
# Unit-test Conditional Edge - Невосстановимая ошибка
#######################################
def test_lifecycle_stops_on_unrecoverable_error():

    """
    Тестируем route unrecoverable_error.
    """

    state = {
        "iteration_count": 1,
        "max_iterations": 5,
        "termination_reason": None,
        "planner_error": {
            "type": "planner_agent_error",
            "message": "Cannot create valid plan",
        },
    }

    # Вызываем Conditional Edge
    route = route_autonomous_lifecycle(state)

    assert route == "unrecoverable_error"



#######################################
# Unit-test Conditional Edge - Human escalation
#######################################

def test_lifecycle_routes_to_human_escalation():

    """
    Тестируем route Human escalation.
    """

    state = {
        "iteration_count": 2,
        "max_iterations": 5,
        "termination_reason": None,
        "human_escalation_required": True,
        "human_escalation_reason": "Write operation requires manual investigation",
        "rca_quality_check": {
            "needs_more_data": True,
        },
    }

    route = route_autonomous_lifecycle(state)

    assert route == "human_escalation_required"


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


#######################################
# Unit-test Conditional Edge - приоритет условий
#######################################
def test_goal_reached_has_priority_over_iteration_limit():

    """
    Тестируем приоритет условий. 
    Когда агент мог достичь цели ровно на последней разрешённой итерации.
    """

    state = {
        "iteration_count": 5,
        "max_iterations": 5,
        "termination_reason": None,
        "human_escalation_required": False,
        "rca_quality_check": {
            "needs_more_data": False,
        },
    }

    route = route_autonomous_lifecycle(state)
    assert route == "goal_reached"


#######################################
# Инвентарный тест
#######################################
def test_autonomous_loop_always_terminates():

    state = {
        "iteration_count": 0,
        "max_iterations": 5,
        "termination_reason": None,
        "human_escalation_required": False,
        "rca_quality_check": {
            "needs_more_data": True,
        },
    }

    executed_iterations = 0

    while True:

        # Обновление state.iteration_count
        state.update(
            advance_iteration_node(state)
        )

        executed_iterations += 1

        assert executed_iterations <= state["max_iterations"]
        
        # Сравнение iteration_count и max_iterations 
        route = route_autonomous_lifecycle(state)

        if route != "continue":
            break

    assert route == "max_iterations_reached"

    assert executed_iterations == 5

    assert state["iteration_count"] == 5
