import os

os.environ.setdefault("OPENAI_API_KEY","unit-test-key-random")
os.environ.setdefault("OPENAI_API_KEY_EMBEDDING","unit-test-embedding-key-random")


import pytest

from sre_agent.state import SupervisorDecision

from sre_agent.graph import (
    dispatch_specialists,
    route_after_evaluator,
)




#######################################################
#  Тестируем создание Объекта SupervisorDecision и его внутренних classmethods
#######################################################
def test_supervisor_decision_removes_duplicates():

    # Определяем Объект класса SupervisorDecision и при создании объекта запускается внтуренний classmethod normalize_required_agents()
    decision = SupervisorDecision(
        required_agents=[
            "kubernetes",
            "runbook",
            "kubernetes",
        ],
        reason=(
            "Live cluster inspection and "
            "runbook guidance are required."
        ),
    )

    # Проверяем уникальность имен агентов
    assert decision.required_agents == ["kubernetes", "runbook"]


# тест пройдет успешно только при создании ValueError, так как  при создании объекта внтуренний classmethod validate_reason() проверет аттрибут reason
def test_supervisor_decision_requires_reason():
    with pytest.raises(ValueError):
        SupervisorDecision(
            required_agents=["kubernetes"],
            reason="   ",
        )

# тест пройдет успешно только при создании ValueError, так как  при создании объекта проверет аттрибут required_agents и тип данных должен быть SupervisorAgentName
def test_supervisor_decision_rejects_unknown_agent():
    with pytest.raises(ValueError):
        SupervisorDecision(
            required_agents=["database"],
            reason="Database investigation required.",
        )



#######################################################
#  Тестируем функцию dispatch_specialists и маршрутизацию
#######################################################
def test_dispatches_kubernetes_specialist():
    """
    Тестируем корректность созданного Объекта Send c Агентом
    """

    # Определение тестовго state
    state = {
        "required_agents": [
            "kubernetes",
        ],
        "supervisor_error": None,
    }

    # Запускаем Агентов FAN-Out
    sends = dispatch_specialists(state)

    assert len(sends) == 1
    assert sends[0].node == "kubernetes_agent_subgraph"



#######################################################
#  Тестируем Multi-agent routing
#######################################################

def test_dispatches_multiple_specialists():

    state = {
        "required_agents": [
            "kubernetes",
            "runbook",
        ],
        "supervisor_error": None,
    }

    sends = dispatch_specialists(state)
    assert len(sends) == 2

    # создаем множество из агентов для сравнения
    nodes = { send.node for send in sends }
    assert nodes == {
        "kubernetes_agent_subgraph", 
        "runbook_agent_node",
    }


#######################################################
#  Тестируем Memory Route
#######################################################
def test_dispatches_memory_specialist():

    state = {
        "required_agents": [
            "memory",
        ],
        "supervisor_error": None,
    }

    sends = dispatch_specialists(state)

    assert len(sends) == 1

    assert sends[0].node == "memory_agent_subgraph"


#######################################################
#  Тестируем Chat
#######################################################
def test_dispatches_chat_specialist():

    state = {
        "required_agents": [
            "chat",
        ],
        "supervisor_error": None,
    }

    sends = dispatch_specialists(state)

    assert len(sends) == 1

    assert sends[0].node == "chat_agent_node"



#######################################################
#  Тестируем Negative routing
#######################################################
def test_dispatch_fails_when_no_specialists():

    state = {
        "required_agents": [],
        "supervisor_error": None,
    }

    # Тест успешен если поднимается ошибка
    with pytest.raises(
        ValueError,
        match="selected no executable specialists",
    ):
        dispatch_specialists(state)




#######################################################
#  Тестируем функцию route_after_evaluator при Evidence недостаточно и control loop evaluator
#######################################################
def test_evaluator_requests_more_data():

    state = {
        "rca_quality_check": {
            "needs_more_data": True,
        },
        "evaluation_retry_count": 0,
    }

    route = route_after_evaluator(state)

    assert route == "need_more_data"

#######################################################
#  Тестируем функцию route_after_evaluator при Evidence достаточно
#######################################################
def test_evaluator_routes_to_final_response():

    state = {
        "rca_quality_check": {
            "needs_more_data": False,
        },
        "evaluation_retry_count": 0,
    }

    route = route_after_evaluator(state)

    assert route == "final_response"

#######################################################
#  Тестируем функцию route_after_evaluator при превышении evaluation_retry_count
#######################################################

def test_evaluator_stops_after_max_retries():
    """
    Важно протестировать - agentic control loop гарантированно завершается
    """

    state = {
        "rca_quality_check": {
            "needs_more_data": True,
        },
        "evaluation_retry_count": 2,
    }

    route = route_after_evaluator(state)

    assert route == "final_response"


