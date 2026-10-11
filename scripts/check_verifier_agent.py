import asyncio

from sre_agent.agents.verifier_agent import verify_goal
from sre_agent.state import (
    AgentGoal,
    ActionObservation,
    VerifierInput,
)

######################################
# Helper функция
######################################

def make_observation(
    action_id: str,
    result: dict,
) -> ActionObservation:
    return ActionObservation(
        action_id=action_id,
        success=True,
        result=result,
        error=None,
    )


async def check_scenario(
    name: str,
    observations: list[ActionObservation],
    expected_goal_reached: bool,
) -> bool:

    goal = AgentGoal(
        description="Проверить текущую готовность Pod payment-api-1",
        success_criteria=["Pod payment-api-1 имеет Ready=True"],
        constraints=["Read-only"],
        max_iterations=3,
    )

    verifier_input = VerifierInput(
        goal=goal,
        observations=observations,
        current_state={
            "iteration_count": 0,
            "max_iterations": 3,
            "completed_step_ids": [],
            "pending_action": False,
        },
    )

    print(f"\n{'=' * 70}")
    print(f"Сценарий: {name}")
    print(f"Ожидаем goal_reached={expected_goal_reached}")

    try:
        # Реальный вызов LLM через verify_goal().
        verification = await verify_goal(verifier_input)

    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return False

    print(verification.model_dump_json(indent=2))

    passed = (verification.goal_reached is expected_goal_reached)


    print(f"Результат: {'PASS' if passed else 'FAIL'}")

    return passed



async def main() -> None:
    # Определение тестовых сценариев 
    # имя теста, observations, expected_goal_reached 
    scenarios = [
        (
            "Tool успешен, но Pod не готов",
            [
                make_observation(
                    action_id="inspect-pod-not-ready",
                    result={
                        "pod_name": "payment-api-1",
                        "ready": False,
                    },
                )
            ],
            False,
        ),
        (
            "Есть доказательство готовности",
            [
                make_observation(
                    action_id="inspect-pod-ready",
                    result={
                        "pod_name": "payment-api-1",
                        "ready": True,
                    },
                )
            ],
            True,
        ),
        (
            "Tool успешен, но данных о Ready нет",
            [
                make_observation(
                    action_id="inspect-pod-name-only",
                    result={
                        "pod_name": "payment-api-1",
                    },
                )
            ],
            False,
        ),
        (
            "Противоречивые наблюдения без времени",
            [
                make_observation(
                    action_id="inspect-pod-a",
                    result={
                        "pod_name": "payment-api-1",
                        "ready": True,
                    },
                ),
                make_observation(
                    action_id="inspect-pod-b",
                    result={
                        "pod_name": "payment-api-1",
                        "ready": False,
                    },
                ),
            ],
            False,
        ),
    ]

    results = []

    # Последовательные вызовы: удобнее читать результаты
    # и разбирать ошибки каждого сценария.
    for name, observations, expected in scenarios:
        passed = await check_scenario(
            name=name,
            observations=observations,
            expected_goal_reached=expected,
        )

        results.append((name, passed))

    print(f"\n{'=' * 70}")
    print("Итоги:")

    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"{status}: {name}")

    if not all(passed for _, passed in results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())