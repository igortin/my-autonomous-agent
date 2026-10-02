import json
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)

from langchain_core.runnables import RunnableConfig

from typing import Literal

from sre_agent.agents.planner_agent import (
    READ_ONLY_AVAILABLE_ACTIONS,
    validate_read_only_plan,
)

from sre_agent.model import model

from sre_agent.state import (
    AgentGoal,
    ExecutionPlan,
    SREAgentState,
)


# Инициализация LLM c структуированным выводом по схеме ExecutionPlan
replanner_model = model.with_structured_output(
    ExecutionPlan,
    method="function_calling",
    strict=False,
)


REPLANNER_SYSTEM_PROMPT = """
You are the Replanner of a read-only autonomous SRE agent.

Create a revised ExecutionPlan using:
- the original AgentGoal;
- completed observations;
- missing success criteria;
- available read-only actions.

Rules:

1. Return only ExecutionPlan.
2. Plan only the missing diagnostic work.
3. Do not repeat a successfully completed step unless the observation
   explicitly shows that retrying is useful.
4. Every executable step must use action_type="read".
5. Never create write, verify, delete, patch, scale, restart, exec, create,
   apply or approval steps.
6. Do not invent resource names or environment facts.
7. Every dependency must refer to an earlier step in the new plan.
8. Every step must contain exactly one AgentAction in its action field.

Use:
- action.action_id: unique within the new plan;
- action.tool: exact tool name from available_actions;
- action.arguments: exact argument names from the tool's args_schema;
- action.expected_result: expected information from this inspection;
- action.risk_level: "read".

Never create analysis or verification steps without an operational tool.
"""

#####################################
# Replanner node
#####################################

async def replanner_node(
        state: SREAgentState,
        config: RunnableConfig,
) -> dict:
    """
    Replanner должен создать пересмотренный новый план c только дополнительными диагностическами шагами для новой итерации lifecycle.
    """

    try:    
        # Читаем цель из state
        raw_goal =  state.get("goal")
        
        # Валидируем цель и получаем объект класса AgentGoal
        goal = AgentGoal.model_validate(raw_goal)

        # Инициализируем новый пересмотренный план
        revised_execution_plan = await replanner_model.ainvoke(
            [
                SystemMessage(content=REPLANNER_SYSTEM_PROMPT),
                HumanMessage(
                    content=json.dumps(
                        {
                            # передаем цель
                            "goal": goal.model_dump(mode="json"),

                            # читаем текущий план из state
                            "previous_plan": state.get("execution_plan"),

                            # читаем список результатов шагов из state
                            "observations": state.get("observations", []),
                            
                            # читаем список missing_criteria заполненный на verifier_node из state
                            "missing_criteria": state.get("replan_feedback",[]),

                            # передаем list of dicts разрешенных действий 
                            "available_actions": [ 
                                action.model_dump(mode="json")
                                for action in READ_ONLY_AVAILABLE_ACTIONS
                            ]
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            ],
            config=config
        )

        # Валидация нового пересмотренного плана и создание объекта по схеме ExecutionPlan
        new_execution_plan = validate_read_only_plan(
            ExecutionPlan.model_validate(revised_execution_plan)
        )

        return {
            # записываем новый пересмотренный execution_plan
            "execution_plan": new_execution_plan.model_dump(mode="json"),

            # обнуляем для следующей интерации lifecycle
            "completed_step_ids": [],

            # обнуляем для следующей интерации lifecycle
            "current_step": None,

            # обнуляем для следующей интерации lifecycle        
            "planner_error": None,
        }

    except Exception as exc:
        return {
            "planner_error": {
                "type": "replanner_error",
                "message": str(exc),
            },
            "execution_plan": None,                 # Удаляем старый план созданный на planner_agent_node (не replanner)
        }

#####################################
# CE route_after_replanner
#####################################
def route_after_replanner(
    state: SREAgentState,
) -> Literal["continue", "stop"]:
    """
    Функция проверяет наличие нового пересмотренного плана и ошибок его генерации
    """
    if state.get("planner_error"):
        return "stop"

    if not state.get("execution_plan"):
        return "stop"

    return "continue"