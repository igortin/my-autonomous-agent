import pytest
from pydantic import ValidationError
from unittest.mock import AsyncMock
from sre_agent.state import ExecutionPlan


from langchain_core.messages import HumanMessage

from sre_agent.autonomy import planner as planner_module

from sre_agent.autonomy.planner import planner_node
from sre_agent.state import AgentGoal


def test_valid_plan() -> None:

    """
    Тестирование валидности создания объекта ExecutionPlan и корректность объектов step.

    Cсылки на зависимости depends_on обязаны быть на существующие step.id
    """
    plan = ExecutionPlan.model_validate(
        {    
            "steps": [
                {
                    "id": "inspect",
                    "description": "Inspect deployment",
                    "agent": "kubernetes",
                    "action_type": "read",
                    "depends_on": [],
                },
                {
                    "id": "verify",
                    "description": "Verify result",
                    "agent": "kubernetes",
                    "action_type": "verify",
                    "depends_on": ["inspect"],
                },
            ]
        }
    )

    assert plan.steps[1].depends_on == ["inspect"]


"""
Параметризация теста в pytest.
Один и тот же тест будет запущен несколько раз с разными значениями аргумента dependencies:
- dependencies = ["missing"]
- dependencies = ["verify"]
"""
@pytest.mark.parametrize(
    "dependencies",
    [["missing"], ["verify"]],
)
def test_invalid_dependency(dependencies: list[str]) -> None:
    """
    Тестирование создание объекта класса ExecutionPlan с steps, в которых зависимоси depends_on на несуществующие step.id.
    """

    with pytest.raises(ValidationError):
        ExecutionPlan.model_validate(
            {
                "steps": [
                    {
                        "id": "verify",
                        "description": "Verify result",
                        "agent": "kubernetes",
                        "action_type": "verify",
                        "depends_on": dependencies,
                    },
                    {
                        "id": "verify",
                        "description": "Verify result",
                        "agent": "kubernetes",
                        "action_type": "verify",
                        "depends_on": dependencies,
                    }
                ]
            }
        )

###############################################
#  Unit Test planner_node 
###############################################
@pytest.mark.asyncio
async def test_planner_node(monkeypatch):

    # Создаем объект класса ExecutionPlan и валидируем при создании 
    expected_execution_plan = ExecutionPlan.model_validate(
       {    
            "steps": [
                {
                    "id": "inspect",
                    "description": "Inspect deployment",
                    "agent": "kubernetes",
                    "action_type": "read",
                    "depends_on": [],
                },
                {
                    "id": "verify",
                    "description": "Verify result",
                    "agent": "kubernetes",
                    "action_type": "verify",
                    "depends_on": ["inspect"],
                },
            ]
        }
    )

    # инициализация фейк модели 
    fake_planner_model = AsyncMock()

    # при вызове ainvoke возращает dict expected_goal
    fake_planner_model.ainvoke.return_value = expected_execution_plan

    # подменяем в модуле planner_module объект planner_model на fake_planner_model
    monkeypatch.setattr(
        planner_module,
        "planner_model",
        fake_planner_model,
    )

    # инициализация фейк цели 
    fake_goal = AgentGoal(
        description=(
            "Ensure payment-api has 3 ready replicas"
        ),
        success_criteria=[
            "deployment/payment-api spec.replicas == 3",
            "deployment/payment-api status.readyReplicas == 3",
        ],
        constraints=[
            "Do not modify unrelated resources",
            "Require human approval before write operations",
        ],
        max_iterations=5,
    )

    # Cоздание объекта AgentGoal и валидация 
    goal = AgentGoal.model_validate(fake_goal)

   # Иницализируем state с атрибуом goal
    state = {
        "goal": goal.model_dump(mode="json"),
        "goal_interpreter_error": None,
    }

    # иницализируем конфиг
    config = {
        "configurable": {
            "user_id": "test-user",
            "thread_id": "test-thread",
        }
    }

    # Вызываем planner_node 
    result = await planner_module.planner_node(        
        state,
        config,
    )

    assert result["execution_plan"] == expected_execution_plan.model_dump(mode="json")

    assert result["current_step"] == None

    assert result["planner_error"] == None


    fake_planner_model.ainvoke.assert_awaited_once()
