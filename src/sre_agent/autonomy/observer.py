##################################
#  Детерминированным Observer
##################################

from sre_agent.state import SREAgentState, StepObservation

from typing import Literal

from sre_agent.autonomy.executor import select_next_executable_step

#####################################
# Observer node
#####################################

def observer_node(
        state: SREAgentState
) -> dict:

    """"
    Наблюдатель приводит в актуальное state после вызова Tool на execution_node.
    
    Приводит атрибуты state в актуальное и корректное состояние, 
    поскольку вызывали Tool и получили результаты на предыдущем шаге в execution_node.

    Отвественость:
    - Интерпретировать результаты выполения Tool
    - Актуализировать state
    """
        
    # Читаем данные записанные в state.pending_step_result на executor_node
    pending = state.get("pending_step_result")

    # Проверяем наличие результата полученного на executor_node
    if not pending:
        return {
            "execution_error": {
                "type": "missing_step_result",
                "message": "Observer received no executor result"
            }
        }

    # Читаем step в формате JSON строки выполннего на executor_node
    step = pending["step"]

    # Читаем фактический результат выполенения step на executor_node  
    raw_result = pending["raw_result"]

    # Читаем из фактического результатат код выполнения Tool  
    ok = bool(raw_result.get("ok", False))


    # Создаем переменные для объекта класса StepObservation
    if ok:
        summary = (
            f"Tool {step['tool_name']} completed "
            f"for step {step['id']}"
        )

        error = None
    else:
        summary = (
            f"Tool {step['tool_name']} failed "
            f"for step {step['id']}"
        )

        error = str(
            raw_result.get(
                "error",
                "Unknown tool error",
            )
        )

    # Создаем новый объект фактического результата выполненного step на execution_node
    observation = StepObservation(
        step_id=step["id"],
        tool_name=step["tool_name"],
        ok=ok,
        summary=summary,
        data=raw_result,
        error=error,
    )


    # Читаем нормализованные факты прошлых шагов из state и добавляем нормализованный факт
    observations = [
        *(state.get("observations")),
        observation.model_dump(mode="json")
    ]

    # Читаем выполенные step IDs и добавляем еще один выполненный на execution_node 
    completed_step_ids = [
        *state.get("completed_step_ids", []),
        step["id"],
    ]

    # LangGraph перезаписывает занчения в state
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
    Функция прверяет execution_plan в state и выполняет передачу контроля на следующую ноду.
    Так происходит выполнение нескольких step одного execution_plan в итерации lifecycle. 
    """
    
    # Проверка ошибок выполнения Tool на executor_node
    # следущие зависимые step-ы не могут быть вызваны при ошибке на пердыдущем шаге.
    if state.get("execution_error"):
        return "stop"

    try:
        # Определение следующего step из атрибута state.execution_plan
         next_step = select_next_executable_step(state)
    
    except Exception:
        return "stop"

    if next_step is not None:
        return "execute_next_step"

    return "verify_goal"    
