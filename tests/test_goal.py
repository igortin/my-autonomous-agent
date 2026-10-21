from langchain_core.messages import HumanMessage
from sre_agent.state import AgentGoal, SREAgentState
import pytest
from pydantic import ValidationError


########################################################
# Тестирование создания объекта SREAgentState и разделения message и goal
########################################################

user_message = HumanMessage(
    content=(
        "Добейся, чтобы deployment payment-api "
        "имел 3 Ready replicas."
    )
)

goal = AgentGoal(
    description="Restore payment-api availability",
    success_criteria=[
        "deployment.status.readyReplicas == 3",
    ],
    constraints=[
        "do not delete namespace",
        "do not modify other deployments",
    ],
    max_iterations=5,
)

initial_state: SREAgentState = {
    "messages": [user_message],
    "goal": goal.model_dump(),
}



########################################################
# Тест 1 — корректная цель
########################################################

def test_agent_goal_can_be_created():

    goal = AgentGoal(
        description="Restore payment-api availability",
        success_criteria=[
            "deployment.status.readyReplicas == 3",
        ],
        constraints=[
            "do not delete namespace",
            "do not modify other deployments",
        ],
        max_iterations=1,
    )

    assert goal.description == "Restore payment-api availability"
    assert goal.success_criteria == ["deployment.status.readyReplicas == 3"]
    assert goal.max_iterations == 1


########################################################
# Тест 2 - Сериализация для LangGraph state
########################################################
def test_agent_goal_is_stored_separately_from_messages():

    goal = AgentGoal(
        description="Restore payment-api availability",
        success_criteria=[
            "deployment.status.readyReplicas == 3",
        ],
        constraints=[
            "do not delete namespace",
            "do not modify other deployments",
        ],
        max_iterations=1,
        deterministic_rules=[],
    )

    state: SREAgentState = {
        "messages": [],
        "goal": goal.model_dump(),
    }


    assert state["messages"] == []

    assert state["goal"] == {
        "description": "Restore payment-api availability",
        "success_criteria": [
            "deployment.status.readyReplicas == 3",
        ],
        "constraints": [
            "do not delete namespace",
            "do not modify other deployments",
        ],
        "max_iterations": 1,
        "deterministic_rules": [],

    }

########################################################
# Тест 3 — запрещён нулевой лимит
########################################################
# Успешно если поднимается ошибка
def test_agent_goal_rejects_zero_iterations():
    with pytest.raises(ValidationError):

        AgentGoal(
            description="Restore payment-api availability",
            success_criteria=[
                "deployment.status.readyReplicas == 3",
            ],
            constraints=[],
            max_iterations=0,
            deterministic_rules=[],
        )


########################################################
# Тест 4 — нужен хотя бы один success criterion
########################################################
def test_agent_goal_requires_success_criterion():
    with pytest.raises(ValidationError):
        AgentGoal(
            description="Restore payment-api availability",
            success_criteria=[],
            constraints=[],
            max_iterations=5,
            deterministic_rules=[],
        )


########################################################
# Тест 5 — неизвестные поля запрещены
########################################################
def test_agent_goal_rejects_unknown_fields():

    with pytest.raises(ValidationError):
        AgentGoal(
            description="Restore payment-api availability",
            success_criteria=[],
            constraints=[],
            max_iterations=5,
            destructive_mode=False,
            deterministic_rules=[],
        )
