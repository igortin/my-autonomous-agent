from langchain_core.messages import AIMessage

from sre_agent.state import (
    AgentGoal,
    SREAgentState,
)


# Сколько раз одинаковый вызов разрешён при одном и том же состоянии среды
MAX_TOOL_CALLS_GLOBAL = 20

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
            "action_history": [],
        }

    try:
        # Валидация цели
        goal = AgentGoal.model_validate(raw_goal)

        # Читаем лимит вызовов инструментов за расследование из состояния 
        # или инициализация по умочанию бюджета вызовов интструмента в рамках всех итериаций lifecycle. 
        max_tool_calls = state.get("max_tool_calls", MAX_TOOL_CALLS_GLOBAL)

        # Проверяем значение лимита числовое 
        if (not isinstance(max_tool_calls, int) or max_tool_calls < 1):
                raise ValueError("max_tool_calls must be a positive integer")

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
            "action_history": [],
            "action_attempts": [],    
            "blocked_actions": [],
            "duplicate_blocked": False,                
            "verification": None,
            "replan_feedback": [],
            "execution_error": None,
            "max_tool_calls": max_tool_calls,
            "investigation_budget_exhausted": False,
        }
    except Exception:
        return {
            "iteration_count": 0,
            "max_iterations": 1,
            "termination_reason": "unrecoverable_error",
            "completed_step_ids": [],
            "pending_step_result": None,
            "observations": [],
            "action_history": [],
            "action_attempts": [],
            "blocked_actions": [],
            "duplicate_blocked": False,            
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
                        "после которой безопасное продолжение невозможно.\n\n" 
                        + "\n\n".join(sections)
                        ))
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
    observations = state.get("observations") or []              # список объектов по схеме ActionObservation сериализоваанных в JSON
    
    sections = ["Диагностическая цель достигнута."]             # контейнер для выводов в AIMessage


    # Добавляем в контейнер
    if description := goal.get("description"):
        sections.append(f"Цель: {description}")

    # Добавляем Вывод в контейнер
    if reason := verification.get("reason"):
        sections.append(f"Вывод:\n{reason}")

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

    """Добавляем собранные результаты шагов в контейнер sections"""
    if observations:

        # Создаем временный контейнер
        observation_lines = []

        for observation in observations:

            # Создаем переменную на основе атрубиутов класса ActionObservation
            status = (
                "Успешно"
                if observation["success"]
                else "Ошибка"
            )

            action_id = observation["action_id"]

            line = f"- {action_id}: {status}"

            if observation.get("error"):
                line += f". {observation['error']}"

            observation_lines.append(line)

        # Добавим все результаты шагов в контейнер sections
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


######################################
#  Node Бюджет вызова инструментов исчерпан 
######################################
def investigation_budget_exhausted_node(
    state: SREAgentState,
) -> dict:

    verification = state.get("verification") or {}

    evidence = verification.get("evidence") or []

    missing = verification.get("missing_criteria") or []

    remaining = verification.get("remaining_work") or []

    sections = [
        "Расследование остановлено: исчерпан бюджет вызовов.",
        (
            "Использовано вызовов: "
            f"{len(state.get('action_attempts') or [])}/"
            f"{state.get('max_tool_calls')}."
        ),
        "Подтверждаемая причина не установлена.",
    ]

    for title, items in (
        ("Собранные подтверждения", evidence),
        ("Не подтверждено", missing),
        ("Что проверить дальше", remaining),
    ):
        if items:
            sections.append(
                title + ":\n"
                + "\n".join(f"- {item}" for item in items)
            )

    return {
        "termination_reason": "investigation_budget_exhausted",
        "messages": [
            AIMessage(content="\n\n".join(sections))
        ],
    }