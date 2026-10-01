from langchain_core.messages import AIMessage

from sre_agent.state import (
    AgentGoal,
    SREAgentState,
)

############################
# Инициализация lifecycle (начальное состояние)
############################

def initialize_lifecycle_node(
        state: SREAgentState,
) -> dict:
    """
    Initialize bounded lifecycle from AgentGoal.

    Must not:
    - call tools;
    - call an LLM;
    - execute plan steps;
    - inspect infrastructure.
    """
    # Читаем цель из state 
    raw_goal = state.get("goal")

    if not raw_goal:
        return {
            "iteration_count": 0,
            "max_iterations": 1,
            "termination_reason": "unrecoverable_error",
        }

    try:
        # Валидация цели
        goal = AgentGoal.model_validate(raw_goal)

        # LangGraph перехватывает вывод и записывает значения в атрибуты состояния SREAgentState
        return {
            "iteration_count": 0,
            "max_iterations": goal.max_iterations,
            "termination_reason": None,
            "human_escalation_required": False,
            "human_escalation_reason": None,
            "completed_step_ids": [],
            "pending_step_result": None,
            "observations": [],
            "verification": None,
            "replan_feedback": [],
            "execution_error": None,            
        }
    except Exception:
        return {
            "iteration_count": 0,
            "max_iterations": 1,
            "termination_reason": "unrecoverable_error",
            "completed_step_ids": [],
            "pending_step_result": None,
            "observations": [],
            "verification": None,
            "replan_feedback": [],
            "execution_error": None,
        }

############################
# Инициализация счётчика
############################

def advance_iteration_node(
    state: SREAgentState,
) -> dict:
    """
    Mark the current autonomous iteration as completed.
    """

    # Читаем изи состояния номер текущей итерации
    current_count = state.get("iteration_count", 0)

    # Читаем изи состояния порог
    max_iterations = state.get("max_iterations")

    if max_iterations is None or max_iterations < 1:
        return {
            "termination_reason": "unrecoverable_error",
        }

    # Увеличиваем номер итерации
    next_count = current_count + 1

    # Дополнительный предохранитель
    if next_count > max_iterations:
        return {
            "iteration_count": current_count,
            "termination_reason": "max_iterations_reached",
        }

    # LangGraph перехватвает и записывает значение в состояние
    return {
        "iteration_count": next_count,
    }    



###################################
# Helper функция для route_after_verification
###################################
def has_unrecoverable_error(
    state: SREAgentState,
) -> dict:

    # контейнер ошибок
    sections = []

     # Показываем исходные ошибки с указанием этапа.
    for field, stage in (
        ("goal_interpreter_error", "Определение цели"),
        ("planner_error", "Планирование"),
        ("execution_error", "Выполнение"),
    ):
        
        # Читаем ошибки возникшие при работе 
        error = state.get(field, None)

        # Добавляем найденную ошибку в контейнер
        if error:
            error_type = error.get("type", "unknown_error")
            message = error.get("message", "Описание отсутствует")

            sections.append(
                f"{stage}: {error_type}\n{message}"
            )


    if sections:
        return {
            "termination_reason": "unrecoverable_error",
            "messages": [
                AIMessage(content=(
                        "Автономный lifecycle остановлен из-за ошибки, "
                        "после которой безопасное продолжение невозможно."
                        "\n\n".join(sections
                        )))
            ],
        }

    return {}


######################################
#  Node Цель достигнута
######################################
def goal_reached_node(
    state: SREAgentState,
) -> dict:
    """Завершить lifecycle и показать пользователю результат."""

    # Читаем из state
    goal = state.get("goal") or {}                              # объект по схеме AgentGoal сериализоваанный в JSON
    verification = state.get("verification") or {}              # объект по схеме GoalVerification сериализоваанный в JSON
    observations = state.get("observations") or []              # список объектов по схеме StepObservation сериализоваанных в JSON
    
    sections = ["Диагностическая цель достигнута."]             # контейнер для выводов в AIMessage


    # Добавляем в контейнер
    if description := goal.get("description"):
        sections.append(f"Цель: {description}")

    # Добавляем рассуждения в контейнер
    if reason := verification.get("reason"):
        sections.append(f"Результат проверки:\n{reason}")

    # Добавляем в контейнер удовлетворенные критерии успешности
    satisfied = verification.get("satisfied_criteria") or []
    if satisfied:
        sections.append(
            "Подтверждённые критерии:\n"
            + "\n".join(f"- {criterion}" for criterion in satisfied)
        )

    # Добавляем в контейнер подтверждения
    evidence = verification.get("evidence") or []
    if evidence:
        sections.append(
            "Подтверждения:\n"
            + "\n".join(f"- {item}" for item in evidence)
        )

    # Добавляем в контейнер результаты шагов
    if observations:
        observation_lines = []

        for observation in observations:
            status = (
                "Успешно"
                if observation.get("ok")
                else "Ошибка"
            )
            tool_name = observation.get("tool_name", "unknown")
            summary = observation.get("summary", "")

            observation_lines.append(
                f"- {tool_name}: {status}. {summary}"
            )

        sections.append(
            "Собранные наблюдения:\n"
            + "\n".join(observation_lines)
        )

    # LangGraph добавляет в state 
    return {
        "termination_reason": "goal_reached",
        "messages": [
            AIMessage(content="\n\n".join(sections))
        ],
    }



######################################
#  Node Достигнут лимит
######################################
def max_iterations_reached_node(
    state: SREAgentState,
) -> dict:
    return {
        "termination_reason": "max_iterations_reached",
        "messages": [
            AIMessage(
                content=(
                    "Автономный lifecycle остановлен: "
                    "достигнут максимальный лимит итераций. "
                    f"Выполнено итераций: "
                    f"{state.get('iteration_count', 0)}."
                )
            )
        ],
    }




######################################
#  Node Невосстановимая ошибка
######################################
def unrecoverable_error_node(
    state: SREAgentState,
) -> dict:
    return {
        "termination_reason": "unrecoverable_error",
        "messages": [
            AIMessage(
                content=(
                    "Автономный lifecycle остановлен из-за ошибки, "
                    "после которой безопасное продолжение невозможно."
                )
            )
        ],
    }








######################################
#  Node Требуется человек
######################################
def human_escalation_node(
    state: SREAgentState,
) -> dict:

    reason = state.get("human_escalation_reason") or (
        "Агент не может безопасно продолжить "
        "без решения человека."
    )

    return {
        "termination_reason": "human_escalation_required",
        "messages": [
            AIMessage(
                content=(
                    "Требуется эскалация человеку.\n\n"
                    f"Причина: {reason}"
                )
            )
        ],
    }

