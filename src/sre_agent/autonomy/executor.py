from sre_agent.state import ExecutionPlan, PlanStep, SREAgentState

from pydantic import ValidationError

from sre_agent.tools.kubernetes import (
    get_node_events_tool,
    get_node_tool,
    get_pod_events_tool,
    get_pod_logs_tool,
    get_pod_tool,
    list_nodes_tool,
    list_pods_tool,
)

import logging

logger = logging.getLogger(__name__)

#####################################
# Helper Функция выбора следующего шага 
#####################################
def select_next_executable_step(
    state: SREAgentState,
) -> PlanStep | None:

    """
    Функция определяет СЛЕДУЮЩИЙ шаг с учётом уже завершённых шагов в state.completed.

    СЛЕДУЮЩИЙ Шаг можно выполнить, только если завершены все шаги, от которых он зависит.
    """

    # читаем сериализованный в json строку объект ExecutionPlan из state
    raw_plan = state.get("execution_plan")

    # проверяем план не пустой
    if not raw_plan:
        raise ValueError("ExecutionPlan is missing")

    # Валидируем объект
    plan = ExecutionPlan.model_validate(raw_plan)

    # Читаем из state все завершенный ранее step id и формируем множество - коллекцию уникальных элементов
    completed = set(
        state.get("completed_step_ids", [])
    )

    # Итерируемся по шагам в execution plan
    for step in plan.steps:

        # Пропускаем шаг если он уже выполенен и переходим к следующему 
        if step.id in completed:
            continue

        # - Формируем множество коллекцию уникальных элементов из зависимостей текущего step.
        # - Проверяем, является ли множество зависимостей в step.depends_on подмножеством множества completed.
        # Тоесть выполнены ли все шаги, от которых зависит текущий шаг?
        dependencies_satisfied = set(step.depends_on).issubset(completed)

        if dependencies_satisfied:
            return step

    return None


#####################################
# Реестр Whitelist Tools ( Security Boundary)
#####################################

# executor сверяет tool_name с реестром и только после этого вызывает tool
READ_ONLY_TOOL_REGISTRY = {
    "list_pods_tool": list_pods_tool,
    "get_pod_tool": get_pod_tool,
    "get_pod_logs_tool": get_pod_logs_tool,
    "get_pod_events_tool": get_pod_events_tool,
    "list_nodes_tool": list_nodes_tool,
    "get_node_tool": get_node_tool,
    "get_node_events_tool": get_node_events_tool,
}

#####################################
# Реестр запрещенных нами Actions
#####################################
FORBIDDEN_ACTION_TYPES = {
    "write",
    "delete",
    "patch",
    "scale",
    "restart",
    "exec",
    "create",
    "apply",
    "verify",
}


#####################################
# Executor node
#####################################
async def executor_node(
        state: SREAgentState,
) -> dict:
    """"
    Node Executor
    Вызывает Tool и записывает фактический результат в state.pending_step_result 

    Отвественость:
    - проверить validated step
    - проверить allowed tool
    - получить raw result
    """
    
    step = None

    try:
        # Определяем СЛУДУЮЩИЙ шаг
        step = select_next_executable_step(state)

        if step is None:
            return {
                "current_step": None,
                "pending_step_result": None,
                "execution_error": None,
            }

        # Определяем AgentAction в СЛУДУЮЩЕМ шаге
        action = step.action

        if step.action_type != "read":
            return {
                "current_step": step.id,
                "pending_step_result": None,
                "execution_error": {
                    "type": "forbidden_action_type",
                    "message": (
                        f"Action type {step.action_type!r} "
                        "is forbidden in read-only mode"
                    ),
                },
                "human_escalation_required": True,
                "human_escalation_reason": (
                    "ExecutionPlan contains a non-read action"
                ),
            }

        if action.risk_level != "read":
            return {
                "current_step": step.id,
                "pending_step_result": None,
                "execution_error": {
                    "type": "forbidden_risk_level",
                    "message": (
                        f"Risk level {action.risk_level!r} "
                        "is forbidden in read-only mode"
                    ),
                },
                "human_escalation_required": True,
                "human_escalation_reason": (
                    "AgentAction is not classified as read-only"
                ),
            }

        # Получаем инструмент из реестра на основе AgentAction
        tool = READ_ONLY_TOOL_REGISTRY.get(action.tool)

        # Проверка на отсутствия инструмента 
        if tool is None:
            return {
                "current_step": step.id,
                "execution_error": {
                    "type": "tool_not_allowed",
                    "message": (
                        f"Tool {step.tool_name!r} "
                        "is not allowed"
                    ),
                },
                "human_escalation_required": True,
                "human_escalation_reason": (
                    "Planner requested an unapproved tool"
                ),
            }


        # Проверяем аргументы шага по args_schema (напрмер схема ListPodsToolInput) инструмента ДО вызова,
        # чтобы ошибка planner'а стала execution_error, а не исключением в графе
        try:
            tool.args_schema.model_validate(action.arguments)
            
        except ValidationError as exc:
            return {
                "current_step": step.id,
                "execution_error": {
                    "type": "invalid_tool_args",
                    "message": (
                        f"Invalid arguments for {action.tool!r}: "
                        f"{exc.errors(include_url=False)}"
                    ),
                    "tool_args": step.tool_args,
                },
            }

        # iteration_count counts completed on lifecycle iterations.
        # The currently executing iteration is therefore count + 1.
        iteration = state.get("iteration_count", 0) + 1

        
        # This log record is emitted BEFORE tool invocation.
        logger.info(
            "agent_action_before_execution iteration=%s step_id=%s action=%s",
            iteration,
            step.id,
            action.model_dump_json(),
        )

        # Вызов асинхронно tool и передать ему аргументы из step.tool_args.
        raw_result = await tool.ainvoke(action.arguments)

        # нормализация сырого результата raw_result, приводим результат к общей структуре/схеме.
        return {
            "current_step": step.id,
            "pending_step_result": {
                "step": step.model_dump(mode="json"),
                "raw_result": raw_result,
            },
            "execution_error": None,
        }

    except Exception as exc:
        return {
            "current_step": step.id if step is not None else None,
            "pending_step_result": None,
            "execution_error": {
                "type": "executor_error",
                "message": str(exc),
            },
        }
