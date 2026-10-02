from unittest.mock import AsyncMock

import pytest

from sre_agent.agents import planner_agent as planner

from sre_agent.state import AgentGoal

from pydantic import ValidationError


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle_limit", [1, 3, 10, 15, 20])
async def test_planner_attempt_limit_is_independent(
    monkeypatch,
    lifecycle_limit,
):
    goal = AgentGoal(
        description="Получить состояние pod",
        success_criteria=["Состояние pod получено"],
        constraints=["Только чтение"],
        max_iterations=lifecycle_limit,
    )

    planner_input = planner.build_planner_input({
        "goal": goal.model_dump(mode="json"),
        "planner_input": None,
    })

    fake_model = AsyncMock()

    # Пустой план не проходит валидацию ExecutionPlan.
    fake_model.ainvoke.return_value = {"steps": []}

    monkeypatch.setattr(
        planner,
        "planner_model",
        fake_model,
    )


    with pytest.raises(ValidationError):
        await planner.create_execution_plan(
            planner_input,
            config={},
        )

    assert fake_model.ainvoke.await_count == 3