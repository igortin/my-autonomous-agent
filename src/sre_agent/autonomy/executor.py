from sre_agent.state import ExecutionPlan, PlanStep, SREAgentState


from sre_agent.tools.kubernetes import (
    get_node_events_tool,
    get_node_tool,
    get_pod_events_tool,
    get_pod_logs_tool,
    get_pod_tool,
    list_nodes_tool,
    list_pods_tool,
)

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
    
    try:
        # Определяем СЛУДУЮЩИЙ шаг
        step = select_next_executable_step(state)

        if step is None:
            return {
                "current_step": None,
                "pending_step_result": None,
                "execution_error": None,
            }

        # Реестр READ_ONLY_AVAILABLE_ACTIONS поддерживает только "read" операции в функции create_execution_plan() в planner_agent
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

        # Проверка атрибут c наименование инструмента пустой
        if not step.tool_name:
            return {
                "current_step": step.id,
                "executor_error": {
                    "type": "missing_tool_name",
                    "message": "Executable step has no tool_name",
                }
            }

        # Получаем инструмент из реестра указанного шаге в execution_plan
        tool = READ_ONLY_TOOL_REGISTRY.get(step.tool_name)

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

        # Вызов асинхронно tool и передать ему аргументы из step.tool_args.
        raw_result = await tool.ainvoke(step.tool_args)

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
            "pending_step_result": None,
            "execution_error": {
                "type": "executor_error",
                "message": str(exc),
            },
        }
