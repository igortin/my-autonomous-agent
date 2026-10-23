import json

import pytest

from unittest.mock import AsyncMock

from sre_agent.autonomy import replanner as replanner_module

from sre_agent.state import ExecutionPlan

from sre_agent.autonomy import observer
from copy import deepcopy



##################################################
# Тестовый pending_step_result из executor_node
##################################################
def make_pending(
    *,
    action_id: str,
    step_id: str,
    success: bool,
) -> dict:
    return {
        "step": {
            "id": step_id,
            "description": "Inspect payment-api Deployment",
            "agent": "kubernetes",
            "action_type": "read",
            "action": {
                "action_id": action_id,
                "tool": "get_deployment_tool",
                "arguments": {
                    "cluster_alias": "test-cluster",
                    "namespace": "default",
                    "deployment_name": "payment-api",
                },
                "expected_result": "Read Deployment replica counts",
                "risk_level": "read",
            },
            "depends_on": [],
        },
        "observation": {
            "action_id": action_id,
            "success": success,
            "result": (
                {"ready_replicas": 1}
                if success
                else None
            ),
            "error": (
                None
                if success
                else "TimeoutError: request timed out"
            ),
        },
    }



@pytest.mark.asyncio
async def test_replanner_recieves_history_and_preserves_it(monkeypatch):
    
    """
    Тестируем ноду Replanner что получает action_history и не затирает.
 
    Проверка двух важных свойств:
    1. История action_history включена в фактический вход LLM.
    2. Обновление плана не стирает action_history.
    """
    
    # Результат выполнения ноды executor_node
    first_pending = make_pending(
        action_id="action-1",
        step_id="step-1",
        success=False,       
    )

    # Определение state для вызова Observer_node
    state = {
        "goal": {
            "description": "Inspect payment-api",
            "success_criteria": [
                "Deployment status is known",
            ],
            "constraints": [],
            "max_iterations": 3,
        },
        "execution_plan": {
            "steps": [first_pending["step"]],
        },
        "pending_step_result": first_pending,
        "replan_feedback": ["Deployment status is known"],
    }



    """ Нода Observer подготоваливает наблюдения и записывает observations и action_history """

    # Читаем наблюдение выполненного действия шага 
    # и сохраняем наблюдение в action_history в state  
    result = observer.observer_node(state)

    # Обновим state результатом из Observer 
    state.update(result)

    # Создадим новый обьект полную копию истории
    history_before = deepcopy(state["action_history"])


    """ Нода Replanner с Mock model получает в аргументе observations и action_history """

    # Используем существующую функцию 
    # с целью генерации фейк Step для генерации фейк плана
    fake_pending_step_result = make_pending(
        action_id = "temporary-action",
        step_id = "new-step-1",
        success=True,       
    )

    # Создаем фейковый НОВЫЙ execution_plan который вернется при вызове Mock
    fake_revised_plan = ExecutionPlan.model_validate(
        {
            "steps": [fake_pending_step_result["step"]],
        }
    )


    # создаем Mock модели
    mocked_model = AsyncMock()

    # устанвливаем возврат фейкового НОВОГО execution_pan при вызов Mock модели 
    mocked_model.ainvoke.return_value = fake_revised_plan

    # Подменеяем в модуле replanner_module модель replanner_module на фейковую mocked_model
    monkeypatch.setattr(
        replanner_module,
        "replanner_model",
        mocked_model,
    )

    # Возращает также фейковый новый пересмотренный execution_plan
    update = await replanner_module.replanner_node(
        state,
        config={},
    )

    # Обновление state результатом из Replanner node
    state.update(update)



    """ Тесты """

    # Проверка выполнения Observer node на ошибки
    assert update["planner_error"] is None

    # Проверка запуска обращения в LLM
    mocked_model.ainvoke.assert_awaited_once()

    # Проверяем input аргумент при вызове модели
    messages = mocked_model.ainvoke.call_args.args[0]

    # Десераилизация JSON строки в dict
    payload = json.loads(messages[1].content)

    # Проверяем что в mocked_model в аргументе был передан action_history с наблюдением
    assert payload["action_history"] == history_before

    # Проверяем наблюдение observation на основе на first_pending 
    record = payload["action_history"][0]
    assert record["success"] is False
    assert record["action"]["tool"] == "get_deployment_tool"

    # Проверка Replanner не выполняет очистки истории trajectory
    assert "action_history" not in update

    # Проверка state что Replanner не изменяет историю
    assert state["action_history"] == history_before    
