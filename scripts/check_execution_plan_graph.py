import asyncio
import json
from langchain_core.messages import HumanMessage
from sre_agent.graph import graph


async def main() -> None:

    config = {
        "configurable": {
            "thread_id": "week8-day4-plan-check",
            "user_id": "igor",
        }
    }
    

    initial_state = {
        "messages": [
            HumanMessage(
                content="Восстанови payment-api до 3 реплик"
            )
        ],
        "evaluation_retry_count": 0,
        "completed_agents": [],
        "relevant_memory_context": {},
    }

    ################################################
    # Вызов граф и остановка после ноды planner_node
    ################################################
    result = await graph.ainvoke(
        initial_state,
        config=config,
        interrupt_after=["planner_node"],
    )

    ################################################
    # Вывод атрибутов состояния
    ################################################
    print("\n=== GOAL ===")
    print(json.dumps(
        result.get("goal"),
        indent=2,
        ensure_ascii=False,
        )
    )

    print("\n=== Execution Plan ===")
    print(json.dumps(
        result.get("execution_plan"),
        indent=2,
        ensure_ascii=False,
        )
    )

    print("\n=== CURRENT STEP ===")
    print(result.get("current_step"))

    print("\n=== PLANNER ERROR ===")
    print(
        json.dumps(
            result.get("planner_error"),
            indent=2,
            ensure_ascii=False,
        )
    )

    assert result.get("goal") is not None
    assert result.get("execution_plan") is not None
    assert result.get("current_step") is None
    assert result.get("planner_error") is None

    print("\n✅ Goal и ExecutionPlan успешно созданы")


if __name__ == "__main__":
    asyncio.run(main())