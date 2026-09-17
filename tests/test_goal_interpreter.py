from unittest.mock import AsyncMock
import pytest
from langchain_core.messages import HumanMessage
from sre_agent.autonomy import goal as goal_module
from sre_agent.state import AgentGoal

#  Unit Test Node
@pytest.mark.asyncio
async def test_goal_interpreter_returns_structured_goal(
    monkeypatch,
):


    # ожидаемый dict
    expected_goal = AgentGoal(
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


    # инициализация фейк модели 
    fake_goal_model = AsyncMock()

    # при вызове ainvoke возращает dict expected_goal
    fake_goal_model.ainvoke.return_value = expected_goal

    # подменяем в модуле goal_module объект goal_interpreter_model на fake_goal_model
    monkeypatch.setattr(
        goal_module,
        "goal_interpreter_model",
        fake_goal_model,
    )

    # описываем state
    state = {
        "messages": [
            HumanMessage(
                content="Восстанови payment-api до 3 реплик"
            )
        ]
    }

    # описываем конфиг
    config = {
        "configurable": {
            "user_id": "test-user",
            "thread_id": "test-thread",
        }
    }

    result = await goal_module.goal_interpreter_node(
        state,
        config,
    )


    assert result["goal"] == expected_goal.model_dump(
        mode="json"
    )

    assert result["goal_interpreter_error"] is None


    
    fake_goal_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_goal_interpreter_handles_model_error(monkeypatch):

    """
    Тест обработки ошибки, node не роняет весь процесс 
    и ошибка записывается в state при LLM error
    """

    fake_goal_model = AsyncMock()

    fake_goal_model.ainvoke.side_effect = RuntimeError("LLM is unavailable")

    monkeypatch.setattr(
        goal_module,
        "goal_interpreter_model",
        fake_goal_model,
    )

    state = {
        "messages": [
            HumanMessage(
                content="Восстанови payment-api до 3 реплик"
            )
        ]
    }

    result = await goal_module.goal_interpreter_node(state, {})

    assert result["goal"] is None

    assert result["goal_interpreter_error"] == {
        "type": "goal_interpreter_structured_output_error",
        "message": "LLM is unavailable"
    }

@pytest.mark.asyncio
async def test_goal_interpreter_handles_missing_human_message():
    """
    Тест отсутствия HumanMessage в state
    
    Вызывается нода goal_interpreter_node но поднимается исключения в функции 
    
    get_latest_human_message([])
    """

    state = {
        "messages": []
    }

    result = await goal_module.goal_interpreter_node(
        state,
        {},
    )

    assert result["goal"] is None

    assert result["goal_interpreter_error"] is not None


    assert "No HumanMessage" in result["goal_interpreter_error"]["message"]

