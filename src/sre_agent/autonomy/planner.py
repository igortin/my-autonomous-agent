from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from langchain_core.runnables import RunnableConfig

from pydantic import ValidationError

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
- Use unique step IDs.
- Every depends_on entry MUST be a character-for-character copy of an
  `id` already assigned to an earlier step in this same plan. Never
  paraphrase, abbreviate or rename a step id when referencing it.
- Before returning the plan, re-check every depends_on list against the
  step ids you actually used.
- Return only ExecutionPlan.
"""

planner_model = model.with_structured_output(ExecutionPlan)

MAX_PLANNER_ATTEMPTS = 3




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


        # История сообщений, к которой при повторных попытках добавляется
        # текст ошибки валидации, чтобы модель исправила именно её.
        messages: list[BaseMessage] = [
            SystemMessage(content=PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=goal.model_dump_json(indent=2)),
        ]

        plan: ExecutionPlan | None = None
        last_error: ValidationError | None = None

        # Retry-цикл: LLM иногда "придумывает" depends_on, не совпадающий
        # дословно ни с одним ранее созданным id шага. Отдаём модели точный
        # текст ошибки pydantic и просим исправить именно это несоответствие.
        for _ in range(MAX_PLANNER_ATTEMPTS):
            if last_error is not None:
                messages.append(
                    HumanMessage(
                        content=(
                            "The previous ExecutionPlan failed validation:\n"
                            f"{last_error}\n\n"
                            "Fix only this issue: every depends_on value must be "
                            "an exact copy of an id already used by an earlier "
                            "step. Return the corrected ExecutionPlan."
                        )
                    )
                )

            raw_plan = await planner_model.ainvoke(messages, config=config)

            try:
                # Проверяем контракт через staticmethod validate_dependencies.
                plan = ExecutionPlan.model_validate(raw_plan)
                break

            except ValidationError as exc:
                last_error = exc
                plan = None

        # Данный exception перехватывается на уровне выше и записывается в атрибут planner_error SREAgentState
        if plan is None:
            raise last_error

        # LangGraph перехватывает вывод и перезаписывает сериализованный dict в атрибуты SREAgentState
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