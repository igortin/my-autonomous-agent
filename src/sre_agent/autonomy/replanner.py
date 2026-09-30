import json
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)

from langchain_core.runnables import RunnableConfig

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
4. Use only allowed read-only tools.
5. Never create write, delete, patch, scale, restart, exec, create,
   apply or approval steps.
6. Use exact tool names and explicit tool_args.
7. Do not invent resource names or environment facts.
8. Every dependency must refer to an earlier step in the new plan.
9. Every step must be a single tool call with action_type="read" and
   a required tool_name. Never create decision, analysis or verification
   steps without a tool.
"""

#####################################
# Replanner node
#####################################

async def replanner_node(
        state: SREAgentState,
        config: RunnableConfig,
) -> dict:
    """
    Replanner должен создать пересмотренный план c только дополнительными диагностическами шагами.
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
        }