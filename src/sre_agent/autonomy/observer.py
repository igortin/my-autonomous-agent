from typing import Literal

from sre_agent.autonomy.executor import select_next_executable_step

from sre_agent.state import (
    ActionObservation,
    PlanStep,
    SREAgentState,
)

from datetime import datetime, timezone


#####################################
# Observer node
#####################################
def observer_node(
        state: SREAgentState
) -> dict:
    """"
    Проверить результат выполненного действия и сохранить наблюдение и историю попыток.
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
        # Валидируем и создаем Step объект класса PlanStep
        step = PlanStep.model_validate(pending["step"])

        # Валидируем и создаем НАБЛЮДЕНИЕ объект класса ActionObservation
        observation = ActionObservation.model_validate(pending["observation"])

        # Проверка соответствия предыдущего собранного результата на шаге и самого шага 
        if observation.action_id != step.action.action_id:
            raise ValueError(
                "Observation action_id does not match the executed action"
            )

        # Создаём новую проверенную запись с исходным действием.
        # Время, уже установленное для наблюдения, сохраняем.
        observation = ActionObservation.model_validate(
            {
                #сериализация обьекта Python-словарь
                **observation.model_dump(mode="python"),
                # дабавляем в наблюдение выполненное действие с ним связанное
                "action": step.action.model_dump(mode="python"),
                "observed_at":  datetime.now(timezone.utc)
            }
        )


        # Чтение всех собранных результатов выполненных шагов из состояния 
        # и добавление Наблюдения текущего шага в контенйер для Verifier
        observations = [
            *(state.get("observations") or []),
            observation.model_dump(mode="json"),
        ]

        # Чтение всех собранных результатов выполненных шагов из состояния 
        # и добавление Наблюдения текущего шага в контенйер для Replanner
        action_history = [
            *(state.get("action_history") or []),
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
            # Перезаписываем список наблюдений в state для Verifier
            "observations": observations,
            # Перезаписываем список наблюдений в state для Replanner
            "action_history": action_history,
            # Перезаписываем список выполненных шагов в state
            "completed_step_ids": completed_step_ids,
            # Подготовливаем и очищаем контейнер для следующего вызова Tool в state
            "pending_step_result": None,
            # Подготовливаем и очищаем для следующего шага в state
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
    "stop",
    "human_escalation", 
]:
    """
    Функция проверяет execution_plan и выполняет передачу контроля 
    на следующий шаг в рамках одной итерации lifecycle. 
    """

    # Читаем ошибку если есть, которая могла появитяс на executor_node из состояния
    error = state.get("execution_error") or {}

    #  Проверка на превышение пыток вызова интсрумента
    if error.get("type") == "duplicate_action_blocked":
        return "human_escalation"


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
