from __future__ import annotations

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig

from sre_agent.model import model
from sre_agent.state import (
    AgentGoal,
    AvailableAction,
    AvailableAgent,
    ExecutionPlan,
    PlannerInput,
    SREAgentState,
)

from sre_agent.tools.kubernetes import (
    get_node_events_tool,
    get_node_tool,
    get_pod_events_tool,
    get_pod_logs_tool,
    get_pod_tool,
    list_nodes_tool,
    list_pods_tool,
)

################################################
# Реестр агентов на основе класса AvailableAgent
################################################

# Список Агентов для контракта PlannerInput
READ_ONLY_AVAILABLE_AGENTS = [
    AvailableAgent(
        name="kubernetes",
        description="Performs read-only Kubernetes diagnostics.",
    ),
]




################################################
# Реестр разрешенных действий класса AvailableAction
################################################

# Список Action для контракта PlannerInput
READ_ONLY_AVAILABLE_ACTIONS = [
    AvailableAction(
        name="list_pods_tool",
        agent="kubernetes",
        action_type="read",
        description="List pods in a namespace.",
        requires_approval=False,
        args_schema=list_pods_tool.args_schema.model_json_schema(),

    ),
    AvailableAction(
        name="get_pod_tool",
        agent="kubernetes",
        action_type="read",
        description="Inspect one Kubernetes pod.",
        requires_approval=False,
        args_schema=get_pod_tool.args_schema.model_json_schema(),
    ),
    AvailableAction(
        name="get_pod_logs_tool",
        agent="kubernetes",
        action_type="read",
        description="Read recent logs from one pod.",
        requires_approval=False,
        args_schema=get_pod_logs_tool.args_schema.model_json_schema(),

    ),
    AvailableAction(
        name="get_pod_events_tool",
        agent="kubernetes",
        action_type="read",
        description="Read Kubernetes events related to one pod.",
        requires_approval=False,
        args_schema=get_pod_events_tool.args_schema.model_json_schema(),
    ),
    AvailableAction(
        name="list_nodes_tool",
        agent="kubernetes",
        action_type="read",
        description="List Kubernetes nodes.",
        requires_approval=False,
        args_schema=list_nodes_tool.args_schema.model_json_schema(),

    ),
    AvailableAction(
        name="get_node_tool",
        agent="kubernetes",
        action_type="read",
        description="Inspect one Kubernetes node.",
        requires_approval=False,
        args_schema=get_node_tool.args_schema.model_json_schema(),

    ),
    AvailableAction(
        name="get_node_events_tool",
        agent="kubernetes",
        action_type="read",
        description="Read events related to one node.",
        requires_approval=False,
        args_schema=get_node_events_tool.args_schema.model_json_schema(),
    ),
]


################################################
# System Prompt Planner
################################################
PLANNER_SYSTEM_PROMPT = """
You are the Planner Agent of an autonomous SRE system.

Your only responsibility is to create an ExecutionPlan.

You receive:
- an explicit AgentGoal;
- current environment knowledge;
- available agents;
- available actions;
- operational constraints.

Separation of responsibilities:

You decide WHAT should be done.
You do not execute HOW it should be done.

Rules:

1. Return only ExecutionPlan.

2. Create the complete plan before execution starts.

3. Use only agents listed in available_agents.

4. Use only action categories represented by available_actions.

5. Never call tools.

6. Never claim that a command, inspection or change has already happened.

7. Do not invent observed environment state.

8. Do not invent cluster names, namespaces or resources that are absent
   from AgentGoal or environment_knowledge.

9. Every step must be a single tool call: tool_name is REQUIRED and must be
   an exact name from available_actions.

10. Never create decision, analysis, summary, approval or verification
    steps without a tool. Analysis of results is done by the Verifier,
    additional inspections are added later by the Replanner.

11. Do not invent future inspection results. If an inspection may be needed
    only depending on earlier results, leave it out of the plan.

12. Preserve all AgentGoal constraints.

13. Every step ID must be unique.

14. Every depends_on value must exactly match an earlier step ID.

15. Do not add conditional steps.

16. This workflow is strictly read-only.

17. Every executable step must use action_type="read".

18. Use only exact tool names from available_actions.

19. Put tool arguments into tool_args using exactly the property names
    from the action's args_schema. Include every required property.
    Never rename arguments (for example, use "cluster_name", not "cluster").

20. Never create write, approval, shell, exec, restart, delete,
    patch, scale, apply or create steps.

21. Do not add a verification tool step. Goal verification is performed
    separately by the Verifier node.

22. Each plan should contain only diagnostic steps that are still required.
"""




################################################
# Модель Planner
################################################

# Модель обязана вернуть данные, соответствующие ExecutionPlan.
planner_model = model.with_structured_output(
    ExecutionPlan,
    method="function_calling",              # включить механизм вызова функции для получения структурированного ответа на стороне OpenAI
    strict=False,                           # отключение строгой проверки схемы на стороне OpenAI
)


################################################
# Helper функция создания контракта PlannerInput
################################################
def build_planner_input(
        state: SREAgentState
) -> PlannerInput:

    """
    Функция создает объект класса PlannerInput на основе значения state.planner_input
    или НОВЫЙ объект собранный в ручками.
    """

    # Читаем цель из state
    raw_goal = state.get("goal")

    # Проверяем цель не пустая
    if raw_goal is None:
        raise ValueError(
            "AgentGoal is missing from state"
        )

    # Валидируем полученную цель из state
    goal = AgentGoal.model_validate(raw_goal)

    # Читаем входной контракт planner_input из state
    raw_planner_input = state.get("planner_input")

    # Если значение не пустое
    if raw_planner_input is not None:

        # Валидируем полученное значение raw_planner_input
        supplied_input = PlannerInput.model_validate(raw_planner_input)

        # Сравниваем planner_input.goal и полученную goal из state
        if supplied_input.goal != goal:
            raise ValueError("PlannerInput goal does not match state goal")

        # Возращаем валидный объект класса PlannerInput созданный на основе значения в state.planner_input
        return supplied_input


    # Возращаем НОВЫЙ собранный объект класса PlannerInput
    return PlannerInput(
        goal=goal,
        environment_knowledge={},
        available_agents=READ_ONLY_AVAILABLE_AGENTS,
        available_actions=READ_ONLY_AVAILABLE_ACTIONS,
    )


################################################
# Helper функция проверки read-only плана
###############################################
def validate_read_only_plan(
    plan: ExecutionPlan,
) -> ExecutionPlan:
    """
    Проверяет, что каждый шаг плана исполним executor в read-only режиме:
    - action_type="read"
    - tool_name из READ_ONLY_AVAILABLE_ACTIONS.

    Шаги-"размышления" (decide/analyze/verify) без tool_name отклоняются,
    чтобы LLM исправила план на повторной попытке, а не executor упал в рантайме.
    """

    allowed_tools = {
        action.name 
        for action in READ_ONLY_AVAILABLE_ACTIONS
    }

    errors: list[str] = []

    for step in plan.steps:
        if step.action_type != "read":
            errors.append(
                f"Step {step.id!r}: action_type must be 'read', "
                f"got {step.action_type!r}"
            )
        if not step.tool_name:
            errors.append(
                f"Step {step.id!r}: tool_name is required."
            )
        elif step.tool_name not in allowed_tools:
            errors.append(
                f"Step {step.id!r}: unknown tool_name {step.tool_name!r}. "
                f"Allowed: {sorted(allowed_tools)}"
            )

    if errors:
        raise ValueError(
            "ExecutionPlan is not executable in read-only mode:\n"
            + "\n".join(errors)
        )

    return plan


###############################################
# Helper функция планирования и создания ExecutionPlan
###############################################
async def create_execution_plan(
    planner_input: PlannerInput,
    config: RunnableConfig,
) -> ExecutionPlan:

    """
    Create and validate an ExecutionPlan.

    This function:
    - calls only the LLM;
    - does not call operational tools;
    - does not mutate graph state;
    - returns a validated ExecutionPlan.
    """

    # Формируем messages на основе System Prompt и PlannerInput (json строки)
    messages = [
        SystemMessage(
            content=PLANNER_SYSTEM_PROMPT
        ),
        HumanMessage(
            content=planner_input.model_dump_json(indent=2)
        ),
    ]

    #  читаем из PlannerInput.goal значение max_iterations 
    MAX_PLANNER_ATTEMPTS = planner_input.goal.max_iterations

    # контейнер для ошибки 
    last_error: Exception | None = None

    # итерируемся и пытаемся создать объект класса ExecutionPlan
    for _ in range(MAX_PLANNER_ATTEMPTS):
        try:

            # Вызываем LLM и создаем объект класса ExecutionPlan    
            raw_plan = await planner_model.ainvoke(
                messages,
                config=config,
            )

            # Валидируем план и создаем объект
            plan = ExecutionPlan.model_validate(raw_plan)

            # Проверим в функции что каждый step является read и прописан разрешенный tool_name
            return validate_read_only_plan(plan)

        except Exception as exc:
            # Записываем текст ошибки в контейнер 
            last_error = exc

            # Добавляем созданный вручную HumanMessage в messages с ошибкой для повторной попытке LLM создать корректный объект класса ExecutionPlan
            messages.append(
                HumanMessage(
                    content=( 
                            "The previous ExecutionPlan failed validation.\n\n"
                            f"{exc}\n\n"
                            "Return a corrected ExecutionPlan. "
                            "Every depends_on value must exactly match "
                            "an earlier step ID. "
                            "Every step must have action_type=\"read\" and "
                            "an exact tool_name from available_actions."
                    )
                )
            )

    # Все попытки исчерпаны - пробрасываем последнюю ошибку
    if last_error is not None:
        raise last_error

    raise RuntimeError("Planner did not produce an ExecutionPlan")



################################################
# Node planner_agent_node
################################################
async def planner_agent_node(
    state: SREAgentState,
    config: RunnableConfig,
) -> dict:
    """
    LangGraph adapter for Planner Agent.
    """
    # Проверяем что пердыдущий шаг создания объекта AgentGoal был успешен
    if state.get("goal_interpreter_error"):
        return {
            "planner_input": None,
            "execution_plan": None,
            "current_step": None,
            "planner_error": {
                "type": "goal_unavailable",
                "message": (
                    "Planner cannot run because "
                    "Goal Interpreter failed"
                ),
            },
        }

    try:
        # Создание контракта PlannerInput
        planner_input = build_planner_input(state)

        # Вызов LLM в функции
        execution_plan = await create_execution_plan(
            planner_input,
            config,
        )

        return {
            "planner_input": planner_input.model_dump(mode="json"),
            "execution_plan": execution_plan.model_dump(mode="json"),
            "current_step": None,
            "planner_error": None,
        }

    except Exception as exc:
        return {
            "execution_plan": None,
            "current_step": None,
            "planner_error": {
                "type": "planner_agent_error",
                "message": str(exc),
            },
        }



################################################
# Condition Edge 
################################################
def route_after_planner(state: SREAgentState) -> str:

    # проверка формирования AgentGoal
    if state.get("goal_interpreter_error"):
        return "stop"

    # проверка формирования ExecutionPlan
    if state.get("planner_error"):
        return "stop"

    # проверка существования ExecutionPlan
    if not state.get("execution_plan"):
        return "stop"

    return "continue"

