from __future__ import annotations

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from sre_agent.model import model
from sre_agent.state import (
    AgentGoal,
    AvailableAction,
    AvailableAgent,
    ExecutionPlan,
    PlannerInput,
    SREAgentState,
)


################################################
# Реестр агентов
################################################
AVAILABLE_AGENTS = [
    AvailableAgent(
        name="kubernetes",
        description=(
            "Inspects Kubernetes resources, performs approved Kubernetes "
            "changes and verifies Kubernetes state."
        ),
    ),
    AvailableAgent(
        name="memory",
        description=(
            "Retrieves previously stored environment and project knowledge."
        ),
    ),
    AvailableAgent(
        name="runbook",
        description=(
            "Finds operational procedures relevant to the goal."
        ),
    ),
    AvailableAgent(
        name="human",
        description=(
            "Reviews and approves write or destructive operations."
        ),
    ),
]

################################################
# Реестр доступных действий 
################################################

# описание разрешённой возможности для планирования
AVAILABLE_ACTIONS = [
    AvailableAction(
        name="inspect_resource",
        agent="kubernetes",
        action_type="read",
        description=(
            "Read the current state of a Kubernetes resource."
        ),
        requires_approval=False,
    ),
    AvailableAction(
        name="inspect_pods",
        agent="kubernetes",
        action_type="read",
        description=(
            "Inspect pods associated with a workload."
        ),
        requires_approval=False,
    ),
    AvailableAction(
        name="inspect_events",
        agent="kubernetes",
        action_type="read",
        description=(
            "Inspect Kubernetes events related to a resource."
        ),
        requires_approval=False,
    ),
    AvailableAction(
        name="retrieve_runbook",
        agent="runbook",
        action_type="read",
        description=(
            "Retrieve a relevant operational runbook."
        ),
        requires_approval=False,
    ),
    AvailableAction(
        name="request_approval",
        agent="human",
        action_type="approval",
        description=(
            "Request human approval before an operational change."
        ),
        requires_approval=False,
    ),
    AvailableAction(
        name="update_resource",
        agent="kubernetes",
        action_type="write",
        description=(
            "Apply an approved change to a Kubernetes resource."
        ),
        requires_approval=True,
    ),
    AvailableAction(
        name="verify_resource",
        agent="kubernetes",
        action_type="verify",
        description=(
            "Verify the final Kubernetes state against goal success criteria."
        ),
        requires_approval=False,
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

9. Place read-only inspection before any write action.

10. If the plan contains a write or destructive operation and an applicable
    constraint requires approval, include an earlier human approval step.

11. Add a final verification step that checks the AgentGoal success criteria.

12. Preserve all AgentGoal constraints.

13. Every step ID must be unique.

14. Every depends_on value must exactly match an earlier step ID.

15. If a later action depends on inspection results, create a decision step.
    Do not invent the future inspection result.
"""

################################################
# Модель для Planner
################################################

# Модель обязана вернуть данные, соответствующие ExecutionPlan.
planner_model = model.with_structured_output(
    ExecutionPlan
)

# Определим количество попыток создания инстанса ExecutionPlan
MAX_PLANNER_ATTEMPTS = 3


################################################
# Helper функция создания контракта PlannerInput
################################################
def build_planner_input(state: SREAgentState) -> PlannerInput:
    """
    Build validated PlannerInput from graph state.

    This function does not call an LLM or tools.
    """

    # Читаем цель из состояния
    raw_goal = state.get("goal")

    if raw_goal is None:
        raise ValueError(
            "AgentGoal is missing from state"
        )

    # Валидируем цель
    goal = AgentGoal.model_validate(raw_goal)

    # Читаем входной контракт для planner из состояния
    raw_planner_input = state.get("planner_input")

    if raw_planner_input is not None:
        # Валидируем входной контракт для planner полученный из состояния
        supplied_input = PlannerInput.model_validate(raw_planner_input)

        # Сравниваем цель указанную в входном контракте для planner полученную из состояния и нашу цель
        if supplied_input.goal != goal:
            raise ValueError("PlannerInput goal does not match state goal")

        # если цели одинаковые
        return supplied_input

    return PlannerInput(
        goal=goal,
        environment_knowledge={},
        available_agents=AVAILABLE_AGENTS,
        available_actions=AVAILABLE_ACTIONS,
    )



################################################
# Helper функция создания входного LLM message для Planner
################################################
def build_planner_messages(
    planner_input: PlannerInput,
) -> list[BaseMessage]:
    """
    Convert PlannerInput into the LLM message contract and concatinate System Prompt.
    """
    return [
        SystemMessage(
            content=PLANNER_SYSTEM_PROMPT
        ),
        HumanMessage(
            content=planner_input.model_dump_json(indent=2)
        ),
    ]


################################################
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

    # Конкатинация System Prompt и PlannerInput
    messages = build_planner_messages(
        planner_input
    )

    # контейнер для ошибки 
    last_error: Exception | None = None

    # итерируемся и пытаемся создать объект класса ExecutionPlan
    for _ in range(MAX_PLANNER_ATTEMPTS):
        try:

            raw_plan = await planner_model.ainvoke(
                messages,
                config=config,
            )

            return ExecutionPlan.model_validate(raw_plan)
        
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
                            "an earlier step ID."
                    )
                )
            )

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

