import json

from unittest.mock import AsyncMock

import pytest

from sre_agent.agents import planner_agent as planner_module
from sre_agent.state import (
    AgentGoal,
    ExecutionPlan,
)

############################################
# Создание ожидаемого плана
# Тестовые данные или объекты, 
# которые pytest.fixture автоматически передаёт в тесты.
############################################
@pytest.fixture
def expected_plan() -> ExecutionPlan:
    return ExecutionPlan.model_validate(
        {
            "steps": [
                {
                    "id": "inspect_deployment",
                    "description": "Inspect the current state of deployment/payment-api",
                    "agent": "kubernetes",
                    "action_type": "read",
                    "depends_on": [],
                },
                {
                    "id": "inspect_pods",
                    "description": "Inspect pods belonging to payment-api",
                    "agent": "kubernetes",
                    "action_type": "read",
                    "depends_on": [
                        "inspect_deployment"
                    ],
                },
                {
                    "id": "determine_remediation",
                    "description": "Determine whether a replica change is required based on inspection results",
                    "agent": "kubernetes",
                    "action_type": "decision",
                    "depends_on": [
                        "inspect_deployment",
                        "inspect_pods",
                    ],
                },
                {
                    "id": "request_approval",
                    "description": "Request human approval before changing deployment replicas",
                    "agent": "human",
                    "action_type": "approval",
                    "depends_on": [
                        "determine_remediation"
                    ],
                },
                {
                    "id": "update_deployment",
                    "description": "Set deployment/payment-api desired replicas to 3 if required",
                    "agent": "kubernetes",
                    "action_type": "write",
                    "depends_on": [
                        "request_approval"
                    ],
                },
                {
                    "id": "verify_deployment",
                    "description": (
                        "Verify spec.replicas == 3 and "
                        "status.readyReplicas == 3"
                    ),
                    "agent": "kubernetes",
                    "action_type": "verify",
                    "depends_on": [
                        "update_deployment"
                    ],
                },
            ]
        }
    )


###############################################
# Unit Test planner_agent_node
###############################################

@pytest.mark.asyncio
async def test_planner_agent_creates_execution_plan(monkeypatch, expected_plan):

    # инициализация фейк модели 
    fake_planner_model = AsyncMock()

    # при вызове ainvoke возращает объект expected_plan - тестовые данные fixture переданные как параметр 
    fake_planner_model.ainvoke.return_value = (
        expected_plan 
    )

    # подменяем в модуле planner_agent.py объект planner_model на fake_planner_model
    monkeypatch.setattr(
        planner_module,
        "planner_model",
        fake_planner_model,
    )

    # Инициализация  объекта класса AgentGoal 
    fake_goal = AgentGoal(
        description=(
            "Ensure payment-api has 3 ready replicas"
        ),
        success_criteria=[
            (
                "deployment/payment-api "
                "spec.replicas == 3"
            ),
            (
                "deployment/payment-api "
                "status.readyReplicas == 3"
            ),
        ],
        constraints=[
            "Do not modify unrelated resources",
            (
                "Require human approval before "
                "write operations"
            ),
        ],
        max_iterations=5,
    )



    # Валидация объекта AgentGoal 
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

    # Вызываем planner agent 
    result = await planner_module.planner_agent_node(
        state,
        config=config,
    )

    assert result["execution_plan"] == expected_plan.model_dump(mode="json")

    assert result["current_step"] == None

    assert result["planner_error"] == None

    fake_planner_model.ainvoke.assert_awaited_once()




###############################################
# Unit Test planner_agent_node получил полный контекст
# goal, environment_knowledge, available_agents, 
# available_actions и constraints
###############################################
@pytest.mark.asyncio
async def test_planner_receives_complete_context(monkeypatch, expected_plan):

    fake_planner_model = AsyncMock()

    fake_planner_model.ainvoke.return_value = (
        expected_plan
    )

    monkeypatch.setattr(
        planner_module,
        "planner_model",
        fake_planner_model,
    )

    test_goal = AgentGoal(
        description=(
            "Ensure payment-api has 3 ready replicas"
        ),
        success_criteria=[
            "spec.replicas == 3",
            "status.readyReplicas == 3",
        ],
        constraints=[
            (
                "Require human approval before "
                "write operations"
            )
        ],
        max_iterations=5,
    )

    
    planner_input_state = {
        "goal": test_goal.model_dump(
            mode="json"
         ),
        "goal_interpreter_error": None,

        "planner_input": {
            "goal": test_goal.model_dump(
                mode="json"
            ),

            "environment_knowledge": {
                "cluster": "docker-desktop-test",
                "namespace": "default",
                "workload": "payment-api",
            },

            "available_agents": [agent.model_dump(mode="json") for agent in planner_module.AVAILABLE_AGENTS],

            "available_actions": [action.model_dump(mode="json") for action in planner_module.AVAILABLE_ACTIONS],
        },
    }

    config = {
        "configurable": {
            "user_id": "test-user",
            "thread_id": "test-thread",
        }
    }


    # Вызов Planner Agent
    await planner_module.planner_agent_node(planner_input_state, config)

    # Читаем все аргументы вызова Planner Agent
    call = fake_planner_model.ainvoke.await_args

    # Читаем аргумент с индексом 0
    messages = call.args[0]

    # Сериализуем тип данных str в dict 
    planner_payload = json.loads(messages[1].content)

    assert planner_payload["goal"]["description"] == test_goal.description

    assert planner_payload["environment_knowledge"]["cluster"] == "docker-desktop-test"

    assert planner_payload["available_agents"]

    assert planner_payload["available_actions"]

    assert planner_payload["goal"][ "constraints"] == test_goal.constraints


###############################################
# Unit Test planner_agent_node при отсуствии AgentGoal 
# и записи ошибки сгенерированной функцией build_planner_input() 
# в атрибут planner_error 
###############################################
@pytest.mark.asyncio
async def test_planner_fails_without_goal():

    result = await planner_module.planner_agent_node(
        {
            "goal": None,
            "goal_interpreter_error": None,
        },
        {
            "configurable": {
                "user_id": "test-user",
                "thread_id": "test-thread",
            }
        },
    )

    assert result["execution_plan"] is None
    assert result["current_step"] is None
    assert result["planner_error"] is not None
    assert result["planner_error"]["type"] == "planner_agent_error"


###############################################
# Unit Test planner_agent_node на ошибку формирования объекта AgentGoal
# на пердыдущем шаге goal_interpreter_node
###############################################
@pytest.mark.asyncio
async def test_planner_stops_after_goal_interpreter_error():

    result = await planner_module.planner_agent_node(
        {
            "goal": None,
            "goal_interpreter_error": {
                "type": "structured_output_error",
                "message": "Invalid goal",
            },
        },
        {
            "configurable": {
                "user_id": "test-user",
                "thread_id": "test-thread",
            }
        },
    )

    assert result["execution_plan"] is None

    assert result["planner_error"] == {
        "type": "goal_unavailable",
        "message": (
            "Planner cannot run because "
            "Goal Interpreter failed"
        ),
    }