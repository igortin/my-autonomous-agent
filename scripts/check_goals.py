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

    requests = [
        "Освободи на colvir-bastion минимум 20 GB.",
        "Снизь consumer lag группы loan-status-consumer ниже 1000.",
        "Восстанови payment-api до 3 реплик.",
    ]

    config = {
            "configurable": {
                "user_id": "igor",
                "thread_id": "week8-day3-test",
            }
        }

    for request in requests:
        
        result = await goal_interpreter_node(
            {"messages": [HumanMessage(content=request)]},
            config,
        )

        print("result :",
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

            print(validated_goal, "\n")


if __name__ == "__main__":
    asyncio.run(main())