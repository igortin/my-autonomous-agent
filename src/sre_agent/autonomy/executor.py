from sre_agent.state import ExecutionPlan, PlanStep, SREAgentState
from pydantic import ValidationError
import logging

from sre_agent.state import ActionObservation

from sre_agent.tools.kubernetes import (
    get_node_events_tool,
    get_node_tool,
    get_pod_events_tool,
    get_pod_logs_tool,
    get_pod_tool,
    list_nodes_tool,
    list_pods_tool,
    get_deployment_tool,
)


from sre_agent.autonomy.duplicate_guard import (
    build_action_attempt,
    get_environment_fingerprint,
    is_duplicate_limit_reached,
    MAX_DUPLICATE_ATTEMPTS,
)

from sre_agent.autonomy.observation import (
    normalize_action_result,
)

from sre_agent.autonomy.lifecycle import MAX_TOOL_CALLS_GLOBAL

# basic configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

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
    "get_deployment_tool": get_deployment_tool,
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
    Вызывает Tool и записывает фактический результат в state.pending_step_result 
    Отвественость:
    - проверить validated step
    - проверить allowed tool
    - получить raw result
    """
    step = None

    # операция распаковки: все элементы полученного списка добавляются по одному в новый список
    previous_attempts = [
        *(state.get("action_attempts") or [])
    ]

    updated_attempts = previous_attempts.copy()
    
    """ Определения следующего шага PlanStep """

    try:

        # Определяем СЛЕДУЮЩИЙ шаг
        step = select_next_executable_step(state)

        if step is None:
            return {
                "current_step": None,
                "pending_step_result": None,
                "execution_error": None,
            }

        # Проверка бюджета вызова инструментов
        max_tool_calls = state.get("max_tool_calls", MAX_TOOL_CALLS_GLOBAL)

        # Считаем количество выполненных попыток  
        # и превышении бюджета вызова инструментов записываем в состояние
        if len(updated_attempts) >= max_tool_calls:
            return {
                "current_step": None,
                "pending_step_result": None,
                "action_attempts": updated_attempts,
                "investigation_budget_exhausted": True,
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
                        f"Tool {action.tool!r} "
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
            validated_arguments = tool.args_schema.model_validate(action.arguments)

            # Сериализуем в dict
            normalized_arguments = validated_arguments.model_dump(mode="json")       

        except ValidationError as exc:
            return {
                "current_step": step.id,
                "execution_error": {
                    "type": "invalid_tool_args",
                    "message": (
                        f"Invalid arguments for {action.tool!r}: "
                        f"{exc.errors(include_url=False)}"
                    ),
                    "tool_args": action.arguments,
                },
            }


        """ Cоздания новой попытки класс ActionAttempt и вызова tool  """

        #  Создаем отпечаток состояния ресурса Deployment 
        environment_fingerprint = get_environment_fingerprint(
            action=action,
            normalized_arguments=normalized_arguments,
            action_history=state.get("action_history") or [],
            args_schema=tool.args_schema,
        )

        #  Создаем кандидата новую Попытку вызова инструмента
        attempt = build_action_attempt(
            action=action,
            normalized_arguments=normalized_arguments,
            environment_fingerprint=environment_fingerprint,
        )

        # Читаем список предыдущих попыток
        # previous_attempts = state.get("action_attempts") or []

        # Защита от превешния порога (занчение 2) повторения идентичных вызовов инструмента
        if is_duplicate_limit_reached(candidate=attempt, attempts=previous_attempts, max_attempts=MAX_DUPLICATE_ATTEMPTS):

            blocked_actions = state.get("blocked_actions") or []

            # Replanner уже получал это действие как заблокированное,
            # а состояние среды с тех пор не изменилось
            already_blocked = any(
                item.get("duplicate_key") == attempt.duplicate_key
                for item in blocked_actions
            )

            if already_blocked:
                return {
                    "current_step": step.id,
                    "pending_step_result": None,
                    "execution_error": {
                        "type": "duplicate_action_blocked",
                        "message": (
                            "Replanner repeated an action that was already "
                            "blocked for the same environment state"
                        ),
                        "tool": action.tool,
                        "duplicate_key": attempt.duplicate_key,
                    },
                    "human_escalation_required": True,
                    "human_escalation_reason": (
                        f"Повторный вызов {action.tool!r} заблокирован повторно: "
                        "план снова содержит действие, которое уже было "
                        "заблокировано при том же состоянии среды."
                    ),
                }            


            # Первый блок: шаг пропускается, решение принимает Verifier
            return {
                "current_step": step.id,
                "pending_step_result": None,
                "execution_error": None,
                "duplicate_blocked": True,
                "blocked_actions": [
                    *blocked_actions,
                    {
                        "duplicate_key": attempt.duplicate_key,
                        "tool": action.tool,
                        "arguments": normalized_arguments,
                        "step_id": step.id,
                        "iteration": state.get("iteration_count", 0) + 1,
                    },
                ],
            }

        #  Записываем обьект попытка вызова иснтрумента в список
        updated_attempts = [
            *previous_attempts,
            attempt.model_dump(mode="json"),
        ]


        """ Выплнения Шага, вызова Инструмента и получения результата и наблюдения ActionObservation. """

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

        try:     
            # Вызов инструмента и полечуение бизнес данных по ресурсу 
            raw_result = await tool.ainvoke(normalized_arguments)
        
        except Exception as exc:
            observation = ActionObservation(
                action_id=action.action_id,
                success=False,
                result=None,
                error=f"{type(exc).__name__}: {exc}",
            )

        # должен работать после успешного выполнения try блока
        else:
        
            # Нормализуем бизнес данные и создаем наблюдение класса ActionObservation
            observation = normalize_action_result(
                action_id=action.action_id,
                raw_result=raw_result,
            )

        logger.info(
            "agent_action_after_execution step_id=%s observation=%s",
            step.id,
            observation.model_dump_json(),
        )

        # в pending_step_result попадает step и observation наблюдение
        return {
            "current_step": step.id,
            "pending_step_result": {
                "step": step.model_dump(mode="json"),
                "observation": observation.model_dump(mode="json"),
            },
            "action_attempts": updated_attempts,
            "execution_error": None,
        }


    except Exception as exc:
        return {
            "current_step": step.id if step is not None else None,
            "pending_step_result": None,
            "action_attempts": updated_attempts,
            "execution_error": {
                "type": "executor_error",
                "message": str(exc),
            },
        }
