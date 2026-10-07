from typing import Literal

from sre_agent.autonomy.executor import select_next_executable_step

from sre_agent.state import (
    ActionObservation,
    PlanStep,
    SREAgentState,
)

#####################################
# Observer node
#####################################
def observer_node(
        state: SREAgentState
) -> dict:
    """"
    Проверить и сохранить результат выполненного действия инструмента в state.
    """
    # Провереям наличие ошибок на Executor.
    if state.get("execution_error"):
        return {}

    # Читаем данные записанные в state.pending_step_result как результата предыдущего step на Executor.
    pending = state.get("pending_step_result")

    # Проверяем нет ни результата предыдущего step, ни исходной ошибки на Executor.
    if not pending:
        return {
            "execution_error": {
                "type": "missing_step_result",
                "message": "Observer received no executor result"
            }
        }

    try:
        # Валидируем и создаем объект класса PlanStep
        step = PlanStep.model_validate(pending["step"])

        # Валидируем и создаем объект класса ActionObservation
        observation = ActionObservation.model_validate(pending["observation"])

        # Проверка соответствия предыдущего собранного результата на шаге и самого шага 
        if observation.action_id != step.action.action_id:
            raise ValueError(
                "Observation action_id does not match the executed action"
            )

        # Чтение всех собранных результатов выполненных шагов из состояния 
        # и добавление предудыщего шага результатов в контейнер  
        observations = [
            *(state.get("observations") or []),
            observation.model_dump(mode="json"),
        ]

        # Чтение всех завершенных step ID и создание контейнера
        completed_step_ids = [
            *(state.get("completed_step_ids") or []),
        ]

        # Добавление предыдущего выполеннего ID шага 
        if step.id not in completed_step_ids:
            completed_step_ids.append(step.id)

        # LangGraph перехватывает и записывает обнровленные контейнеры в состояние  
        return {
            # Обновляем список результатов шагов
            "observations": observations,
            # Обновляем список выполненных шагов
            "completed_step_ids": completed_step_ids,
            # Подготовливаем и очищаем контейнер для следующего вызова Tool
            "pending_step_result": None,
            # Подготовливаем и очищаем для следующего шага
            "current_step": None,
        }

    except (KeyError, TypeError, ValueError) as exc:
        return {
            "pending_step_result": None,
            "execution_error": {
                "type": "invalid_action_observation",
                "message": str(exc),
            },
        }


##################################
# Condition Edge router_after_observer
##################################
def route_after_observer(
        state: SREAgentState
) -> Literal[
    "execute_next_step",
    "verify_goal",
    "stop"
]:
    """
    Функция проверяет execution_plan и выполняет передачу контроля 
    на следующий шаг в рамках одной итерации lifecycle. 
    """
    
    # Проверка ошибок выполнения Tool на Executor
    # следущие зависимые step-ы не могут быть вызваны при ошибке на предыдущем шаге.
    if state.get("execution_error"):
        return "stop"

    # Читаем все результаты предыдущих шагов
    observations = state.get("observations") or []
    
    if observations:
        # Проверка результата ПОСЛЕДНЕГО шага на ошибки контракта
        try:
            latest_observation = ActionObservation.model_validate(observations[-1])
        except (TypeError, ValueError):
            return "stop"

        """При неудачном последнем шаге"""
        # После неудачного action зависимые шаги старого плана автоматически не выполняются.
        # Происходит переход к ноде Verifier и завершается текущая итерация.
        # Если цель не достигнута, Replanner сможет пересмотреть план на основе ошибки. 
        if not latest_observation.success:
            return "verify_goal"


    """При успешном последнем шаге"""
    try:
        # Определение следующего step из атрибута state.execution_plan
         next_step = select_next_executable_step(state)
    
    except Exception:
        return "stop"

    if next_step is not None:
        return "execute_next_step"

    return "verify_goal"   
