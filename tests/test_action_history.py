from copy import deepcopy

import pytest

from pydantic import ValidationError

from sre_agent.autonomy.lifecycle import initialize_lifecycle_node

from sre_agent.autonomy.observer import observer_node

from sre_agent.state import ActionObservation

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


#########################################
#  Сохраняются действие и результат
#########################################
def test_observer_records_action_result():
    """
    Тестирование работы observer_node на добавление action обьекта AgentAction в observation наблюдение
    и запись в action_history для Replanner
    """

    # Определение state класса SREAgentState 
    state = {
        "observations": [],
        "action_history": [],
        "completed_step_ids": [],
        "pending_step_result": make_pending(
            step_id="step-1", 
            action_id="action-1",
            success =True
        ),
    }

    
    # новый обьект полная копия состояния
    original_state = deepcopy(state)

    # Вызываем Observer и создаем новый обьект состояние
    # обновлем состояние путем добавления наблюдений в observations, action_history и completed_step_ids
    result = observer_node(state)

    # Проверка отсуствия поля в Observer вывода  
    assert "execution_error" not in result

    # Проверка в Observer выводе присуствия наблюдения в поле action_history
    assert len(result["action_history"]) == 1

    # Валидация при создании обьекта наблюдения класса ActionObservation
    observation = ActionObservation.model_validate(result["action_history"][0])

    # Проверка атрибутов обьекта наблюдения observation
    assert observation.action_id == "action-1"
    assert observation.success is True
    assert observation.observed_at is not None

    # Проверка присуствия намерения действия класса AgentAction в наблюдении
    assert observation.action is not None
    assert observation.action.tool == "get_deployment_tool"

    # Проверка наличия названия ресурса в намеринии действия класса AgentAction
    assert observation.action.arguments["deployment_name"] == "payment-api"

    # Проверка успешной подготовки и очистки для следующего вызова Tool в обновленном состоянии 
    assert result["pending_step_result"] is None

    # Observer возвращает результат, не изменяя входной state.
    assert state == original_state




#########################################
#  Тест 2. Ошибка тоже сохраняется
#########################################
def test_observer_records_failed_attempt():
    """
    Тестирование работы observer_node на добавление action обьекта AgentAction с не успещным резултатом выполения шага в observation наблюдение
    и их сохранении.
    """

    state = {
        "pending_step_result": make_pending(
            action_id="action-failed",
            step_id="step-1",
            success=False,
        ),
    }
    
    # Вызываем Observer и создаем НОВЫЙ обьект состояние
    # обновлем состояние путем добавления наблюдений в observations, action_history и completed_step_ids
    result = observer_node(state)

    observation = ActionObservation.model_validate(
        result["action_history"][0]
    )

    # Проверка атрибутов обьекта наблюдения observation
    assert observation.success is False
    assert observation.result is None
    assert "TimeoutError" in observation.error
    assert observation.action is not None
    assert observation.action.tool == "get_deployment_tool"


#########################################
# Тест 3. История растёт после смены на новый план
#########################################
def test_history_survives_plan_prghres_reset():

    # Первичное состоняие 
    state = {
        "pending_step_result": make_pending(
            action_id="action-1",
            step_id="step-1",
            success=False,
        ),
    }

    result = observer_node(state)

     
    # Обновление состояния
    state.update(result)

    # Создаем новый обьект полная копия наблюдения из state после обновления
    first_record_trajectory = deepcopy(state["action_history"][0])

    # Обновлем state и имитируем выполнение нового step из пересмотренного новго executon_plan сформированного на Replanner 
    state.update(
            {
                "completed_step_ids": [],                       
                "current_step": None,
                "iteration_count": 1,                           # <-- указываем что новая итерация 
                "pending_step_result": make_pending(            
                    action_id="action-2",
                    step_id="step-1",
                    success=True,                               # <-- указываем что результаты нового шага
                ),
            }
        )

    # Обновление состояния
    update = observer_node(state)

    assert update["action_history"][0] == first_record_trajectory

    # Проверяем рузультат выполенения действия в наблюдении который относится к шагу плана итерации 0 lifecycle агента
    assert update["action_history"][0]["success"] is False

    # Проверяем рузультат выполенения действия в наблюдении который относится к шагу плана итерации 1 lifecycle агента
    assert update["action_history"][1]["success"] is True


######################################
# Тест 4. Новая цель очищает историю
######################################
def test_initialize_lifecycle_clears_action_history():
    """
    Тестируем initialize_lifecycle_node() на сброс истории попыток наблюдлений (trajectory) при каждой НОВОЙ ЦЕЛИ.
    """
    # Определеям состояние
    state = {
        "goal": {
            "description": "Inspect payment-api",
            "success_criteria": [
                "Deployment status is known",
            ],
            "constraints": [],
            "max_iterations": 3,
        },
        "action_history": [
            {"old": "record"}
            ],
    }

    
    # Инициализируем Итерацию lifecycle и очищаем историю поптыток и наблюдлений (trajectory).
    update = initialize_lifecycle_node(state)

    # Провереям границу: история относится к текущей цели.
    assert update["action_history"] == []


##################################################
# Тест 5. Несовпадающие идентификаторы отклоняются
##################################################
def test_observation_rejects_mismatched_action_id():
    """
    Тестирование валидации при создании обьекта ActionObservation (наблюдение)

    Статический метод - Проверка идентификаторов которые долджны совпадать в наблюдении и намерении действии AgentAction.
    """
    # Определяем тестовый результат выполнения шага на executor_node 
    pending = make_pending(
        action_id="action-1",
        step_id="step-1",
        success=True,
    )

    with pytest.raises(
        ValidationError,
        match="Observation action_id must match",
    ):
        ActionObservation.model_validate(
            {
                **pending["observation"],
                "action": {
                    **pending["step"]["action"],            # <-- записываем намерение действия AgentAction
                    "action_id": "another-action",          # <-- заменяем значение в AgentAction           
                },
            }
        )