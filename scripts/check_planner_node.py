import asyncio
import json
from langchain_core.messages import HumanMessage
from sre_agent.autonomy.planner import planner_node
from sre_agent.state import AgentGoal, ExecutionPlan



async def main():
    """
    Unit Test проверка работы функции planner_node()
    """

    #################################
    # Инициализация state
    #################################

    # инициализация фейк цели 
    goal = AgentGoal(
        description=(
            "Ensure payment-api has 3 ready replicas"
        ),
        success_criteria=[
            "deployment/payment-api spec.replicas == 3",
            "deployment/payment-api status.readyReplicas == 3",
        ],
        constraints=[
            "Do not modify unrelated resources",
            "Require human approval before write operations",
        ],
        max_iterations=5,
    )

    # Cоздание объекта AgentGoal и валидация 
    goal = AgentGoal.model_validate(goal)

   # Иницализируем state с атрибуом goal
    state = {
        "goal": goal.model_dump(mode="json"),
        "goal_interpreter_error": None,
    }

    #################################
    # Инициализация config
    #################################

    config = {
            "configurable": {
                "thread_id": "week8-day4-planner-node-check",
                "user_id": "igor",
            }
        }

    #################################
    # Инициализация state
    #################################
    
    result = await planner_node(
        state,
        config,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )

    if result["execution_plan"] is not None:
  
          # Сериализуем result["goal"] dict в объект класса AgentGoal с валидацией
          validated_execution_plan = ExecutionPlan.model_validate(
              result["execution_plan"]
          )
          print("\nValidated object:")
  
          print(validated_execution_plan)


if __name__ == "__main__":
    asyncio.run(main())