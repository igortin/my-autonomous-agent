from langchain_core.messages import HumanMessage, SystemMessage

from langchain_core.runnables import RunnableConfig

from sre_agent.model import model

from sre_agent.state import (
    AgentGoal,
    ExecutionPlan,
    SREAgentState,
)


PLANNER_SYSTEM_PROMPT = """
You are the Planner of an autonomous SRE agent.

Create a multi-step ExecutionPlan for the supplied AgentGoal.

Rules:
- Create the full plan before any step is executed.
- Plan observable inspection before proposing a change.
- Include verification against the goal's success criteria.
- Preserve every constraint from AgentGoal.
- A plan is a proposal, not evidence that an action happened.
- Do not call tools or claim to have inspected the environment.
- Do not invent cluster, namespace, credentials or observed failures.
- Mark write or destructive operations clearly in action_type.
- Do not treat a write step as permission to execute it.
- If a decision depends on inspection results, describe a conditional
  decision step; do not invent its outcome.
- Use unique step IDs and depends_on references to earlier steps.
- Return only ExecutionPlan.
"""

planner_model = model.with_structured_output(ExecutionPlan)




async def planner_node(
    state: SREAgentState,
    config: RunnableConfig,
) -> dict:

    try:

        # Проверка наличия exception при создании Объекта класса AgentGoal в предыдущей goal_interpreter_node 
        if state.get("goal_interpreter_error"):
            return {
                "execution_plan": None,
                "current_step": None,
                "planner_error": {
                    "type": "goal_unavailable",
                    "message": "Goal Interpreter failed",
                },
            }

        # Читаем dict из state
        raw_goal = state.get("goal")

        if raw_goal is None:
            raise ValueError("AgentGoal is missing from state")

        # Используем staticmethod для создания Объекта класса AgentGoal
        goal = AgentGoal.model_validate(raw_goal)


        # Создаем Объект класса ExecutionPlan на основе system prompt и goal приведенный в строки
        plan: ExecutionPlan = await planner_model.ainvoke(
            [
                SystemMessage(content=PLANNER_SYSTEM_PROMPT),
                HumanMessage(
                    content=goal.model_dump_json(indent=2)
                )
            ],
            config=config
        )

        # Проверяем контракт через staticmethod validate_dependencies.
        plan = ExecutionPlan.model_validate(plan)

        # LangGraph перехватывает вывод и перезаписывает сериализованный dict в поля SREAgentState
        return {
            "execution_plan": plan.model_dump(mode="json"),
            "current_step": None,
            "planner_error": None,
        }

    except Exception as exc:
        return {
            "execution_plan": None,
            "current_step": None,
            "planner_error": {
                "type": "planner_error",
                "message": str(exc),
            },
        }



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