from sre_agent.model import model

from sre_agent.state import GoalVerification

import json

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig
from sre_agent.state import AgentGoal, SREAgentState

from sre_agent.autonomy.lifecycle import has_unrecoverable_error
from typing import Literal

VERIFIER_SYSTEM_PROMPT = """
You are the Verifier of a read-only autonomous SRE agent.

Your responsibility is to determine whether the informational
AgentGoal has been reached.

Use only:
- AgentGoal;
- completed StepObservations.

Rules:
1. Return only GoalVerification.
2. Check every success criterion separately.
3. A criterion is satisfied only when supported by an observation.
4. Do not invent Kubernetes state, logs, events or root causes.
5. If evidence is insufficient, set goal_reached=false.
6. Put all missing information into missing_criteria.
7. Tool execution success does not automatically mean goal success.
8. goal_reached=true only when every success criterion is supported.
9. If a criterion requires data that the read-only tools cannot provide
   (for example more than 20 log lines, logs of a previous container run,
   or saving artifacts), treat the closest achievable evidence as
   sufficient for that criterion and explain this in the reasoning.
   Do not request replanning for capabilities the agent does not have.
"""

# Инициализация LLM с структуированным выводом по схеме 
verifier_model = model.with_structured_output(
    GoalVerification
)

#####################################
# Verifier node
#####################################
async def verifier_node(
        state: SREAgentState,
        config: RunnableConfig,
        ) -> dict:

    try:
        # Читаем цель из state
        raw_goal= state.get("goal")

        # Валидируем цель и получаем объект класса AgentGoal
        goal = AgentGoal.model_validate(raw_goal)


        # Читаем список нормалиованных результатов выполненных прошлых шагов   
        observations = state.get(
            "observations",
            [],
        )

        # Вызов LLM и выполнеям проверку достижения goal.succes_criteries на основе результатов выполненных шагов
        verification = await verifier_model.ainvoke(
            [
                SystemMessage(content=VERIFIER_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(
                    {
                        "goal": goal.model_dump(mode="json"),
                        "observations": observations,
                    },
                    ensure_ascii=False,
                    indent=2,
                )),
            ],
            config=config
        )

        
        # Валидируем Оценку достаточности шагов и получаем объект класса GoalVerification
        result = GoalVerification.model_validate(
            verification
        )

        # LangGraph перехватывает и записывает в state объект GoalVerification (решение Verifier) и список missing_criteria
        return {
            "verification": result.model_dump(mode="json"),
            "replan_feedback": result.missing_criteria

        }

    except Exception as exc:
        return {
            "verification": None,
            "execution_error": {
                "type": "verifier_error",
                "message": str(exc),
            },
        }


#####################################
# Conditional Edge route_after_verification
#####################################

def route_after_verification(
    state: SREAgentState
) -> Literal[
        "goal_reached",
        "replan",
        "max_iterations_reached",
        "unrecoverable_error",
        "human_escalation_required",
]:
    """
    Порядок проверок здесь принципиален:
        1. Ошибка.
        2. Human escalation.
        3. Goal reached.
        4. Max iterations.
        5. Replan.
    """

    # проверка наличия ошибок на какой-либо предыдущей ноде
    if has_unrecoverable_error(state):
        return "unrecoverable_error"

    # проверка наличия ошибок на предыдущей execution_node
    if state.get("execution_error"):
        return "unrecoverable_error"

    # проверяем нужно ли пользоатвельское согласие
    if state.get("human_escalation_required", False):
        return "human_escalation_required"

    # читаем Оценку достаточности шагов по схеме GoalVerification
    verification = state.get("verification")

    # определяем маршрут
    if verification and verification.get("goal_reached"):
        return "goal_reached"

    # читаем значение текущей итерации lifecycle 
    iteration_count = state.get("iteration_count",0)

    # читаем значение разрешенное количество итераций lifecycle 
    max_iterations = state.get("max_iterations", 1)

    # определяем маршрут
    if iteration_count >= max_iterations:
        return "max_iterations_reached"

    return "replan"