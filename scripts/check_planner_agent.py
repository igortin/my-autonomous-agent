import asyncio
import json
from sre_agent.agents.planner_agent import planner_agent_node
from sre_agent.state import AgentGoal


async def main():

    goal = AgentGoal(
        description=(
            "Ensure payment-api has 3 ready replicas"
        ),
        success_criteria=[
            (
                "deployment/payment-api "
                "spec.replicas == 3"
            ),
            (
                "deployment/payment-api "
                "status.readyReplicas == 3"
            ),
        ],
        constraints=[
            "Do not modify unrelated resources",
            (
                "Require human approval before "
                "write operations"
            ),
        ],
        max_iterations=5,
    )

    state = {
        "goal": goal.model_dump(mode="json"),
        "goal_interpreter_error": None,
    }

    config = {
        "configurable": {
            "thread_id": (
                "week8-day5-planner-agent-check"
            ),
            "user_id": "igor",
        }
    }

    # Рельаный вызов Planner Agent
    result = await planner_agent_node(
        state,
        config,
    )

    # Вывод сериализованного результата в str
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())