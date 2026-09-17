import asyncio
import json
from langchain_core.messages import HumanMessage
from sre_agent.autonomy.goal import goal_interpreter_node
from sre_agent.state import AgentGoal

async def main():
    """
    Unit Test проверка работы функции goal_interpreter_node()
    на запросе юзера
    """
    state = {
        "messages": [
            HumanMessage(
                content=(
                    "Восстанови payment-api до 3 реплик"
                )
            )
        ]
    }

    config = {
        "configurable": {
            "user_id": "igor",
            "thread_id": "week8-day3-test",
        }
    }

    result = await goal_interpreter_node(
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


    if result["goal"] is not None:

        # Сериализуем result["goal"] dict в объект класса AgentGoal с валидацией
        validated_goal = AgentGoal.model_validate(
            result["goal"]
        )
        print("\nValidated object:")

        print(validated_goal)

if __name__ == "__main__":
    asyncio.run(main())