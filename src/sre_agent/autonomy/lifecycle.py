from typing import Literal

from langchain_core.messages import AIMessage

from sre_agent.state import (
    AgentGoal,
    SREAgentState,
    TerminationReason,
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

    # Читаем цель изи состояния 
    goal_data = state.get("goal")

    if not goal_data:
        return {
            "iteration_count": 0,
            "max_iterations": 1,
            "termination_reason": "unrecoverable_error",
        }

    try:
        # Валидация цели
        goal = AgentGoal.model_validate(goal_data)

        # LangGraph перехватывает вывод и записывает значения в атрибуты состояния SREAgentState
        return {
            "iteration_count": 0,
            "max_iterations": goal.max_iterations,
            "termination_reason": None,
            "human_escalation_required": False,
            "human_escalation_reason": None,
        }
    except Exception:
        return {
            "iteration_count": 0,
            "max_iterations": 1,
            "termination_reason": "unrecoverable_error",
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




################################
# Инициализация lifecycle router
################################
LifecycleRoute = Literal[
    "continue",
    "goal_reached",
    "max_iterations_reached",
    "unrecoverable_error",
    "human_escalation_required",
]

###################################
# Helper функция для route_autonomous_lifecycle
###################################
def has_unrecoverable_error(
    state: SREAgentState,
) -> bool:
    """
    Return True only for errors that make safe continuation impossible.
    """

    return any(
        [
            state.get("goal_interpreter_error"),
            state.get("planner_error"),
            state.get("supervisor_error"),
            state.get("aggregation_error"),
        ]
    )


###################################
# Conditional edge
###################################
def route_autonomous_lifecycle(
    state: SREAgentState,
) -> LifecycleRoute:
    """
    Decide whether the autonomous lifecycle may continue.

    Priority:
    1. already terminated;
    2. unrecoverable error;
    3. human escalation;
    4. goal reached;
    5. iteration limit;
    6. continue.
    """

    # читаем значение из состояния 
    termination_reason = state.get("termination_reason")

    if termination_reason == "unrecoverable_error":
        return "unrecoverable_error"

    if termination_reason == "human_escalation_required":
        return "human_escalation_required"

    if termination_reason == "goal_reached":
        return "goal_reached"

    if termination_reason == "max_iterations_reached":
        return "max_iterations_reached"

    # Вызов helper функции при невозможности безопасного продолжения lifecycle
    if has_unrecoverable_error(state):
        return "unrecoverable_error" 

    # читаем значение из состояния
    if state.get("human_escalation_required", False):
        return "human_escalation_required"

    # читаем значение из состояния
    quality = state.get("rca_quality_check")

    # Проверяем объект класса RCAQualityCheck и его атрибута 
    if quality and not quality.get("needs_more_data", True):
        return "goal_reached"

    # читаем значение текщей итерации из состояния
    iteration_count = state.get("iteration_count", 0)

    # читаем значение порога из состояния 
    max_iterations = state.get("max_iterations")

    if max_iterations is None or max_iterations < 1:
        return "unrecoverable_error"

    # Проверка превышения порога
    if iteration_count >= max_iterations:
        return "max_iterations_reached"

    return "continue"

######################################
#  Node Цель достигнута
######################################
def goal_reached_node(
    state: SREAgentState,
) -> dict:
    return {
        "termination_reason": "goal_reached",
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

