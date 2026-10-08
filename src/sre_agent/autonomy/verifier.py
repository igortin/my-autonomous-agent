from typing import Literal

from langchain_core.runnables import RunnableConfig

from sre_agent.agents.verifier_agent import verify_goal

from sre_agent.autonomy.lifecycle import has_unrecoverable_error

from sre_agent.state import (
    AgentGoal,
    ActionObservation,
    SREAgentState,
    VerifierInput,
)


################################################
# адаптером между state графа и агентом проверки 
################################################
async def verifier_node(
        state: SREAgentState,
        config: RunnableConfig,
        ) -> dict:

    try:
        # Читаем цель из state
        raw_goal= state.get("goal")

        # Валидируем цель и получаем объект класса AgentGoal
        goal = AgentGoal.model_validate(raw_goal)


        # Cписок нормалиованных JSON результатов выполненных прошлых шагов
        observations = [
            ActionObservation.model_validate(item).model_dump(mode="json")
            for item in (state.get("observations") or [])
        ]

        # Создаем объект класса 
        verifier_input = VerifierInput(
            goal=goal,
            observations=observations,
            current_state={
                "iteration_count": state.get(
                    "iteration_count", 0
                ),
                "max_iterations": state.get(
                    "max_iterations"
                ),
                "completed_step_ids": state.get(
                    "completed_step_ids"
                ) or [],
                "pending_action": (
                    state.get("pending_step_result") is not None
                ),
            },
        )

        
        # Вызываем оценку достижение цели
        result = await verify_goal(
            verifier_input,
            config=config,
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
    
    # Ошибки имеют наивысший приоритет.
    # Проверка наличия ошибок на какой-либо предыдущей ноде
    if has_unrecoverable_error(state):
        return "unrecoverable_error"

    # Проверяем нужно ли пользовательское согласие
    if state.get("human_escalation_required", False):
        return "human_escalation_required"

    # Решение advance_iteration_node действительно управляет маршрутом
    termination_reason = state.get("termination_reason")

    if termination_reason in {
            "max_iterations_reached",
            "unrecoverable_error",
    }:
        return termination_reason


    # Проверяем результат одной завершённой итерации lifcycle
    verification = state.get("verification") or {}


    # Сначало проверим достигнута ли цель
    if verification.get("goal_reached") is True:
        return "goal_reached"


    """ Проверка лимита количеств итераций lifecycle """

    max_iterations = state.get("max_iterations")

    iteration_count = state.get("iteration_count", 0)

    if max_iterations is None or max_iterations < 1:
        return "unrecoverable_error"

    if iteration_count >= max_iterations:
        return "max_iterations_reached"
    
    return "replan"