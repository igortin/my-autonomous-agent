from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from sre_agent.agents import verifier_agent

from sre_agent.state import (
    ActionObservation,
    AgentGoal,
    GoalVerification,
    PodReadyRule,
    VerifierInput,
)


# Критерий принадлежайщий Python
READY_CRITERION = "Pod payment-api-1 имеет Ready=True"

# Критерий принадлежайщий LLM
RCA_CRITERION = "Причина CrashLoopBackOff установлена"


##########################################################
# Helper функция генерации тестового обьекта класса VerifierInput
###########################################################
def make_input(
    ready: str,
    *,
    mixed: bool = False,
) -> VerifierInput:

    # Определяем список успешных детермированных критериев
    criteria = [READY_CRITERION]

    # Если true, добавлеям в список успешный критерий принадлежащий LLM
    if mixed:
        criteria.append(RCA_CRITERION)

    # Возращаем тестовый объект
    return VerifierInput(
                goal=AgentGoal(
                    description="Проверить payment-api-1",
                    success_criteria=criteria,
                    deterministic_rules=[
                        PodReadyRule(
                            kind="pod_ready",
                            criterion=READY_CRITERION,
                            cluster_alias="docker-desktop",
                            namespace="payments",
                            pod_name="payment-api-1",
                        ),
                    ],
                    constraints=["Read-only"],
                    max_iterations=3,
                ),
                observations=[
                    ActionObservation(
                        action_id="inspect-pod",
                        success=True,
                        result={
                            "action": "get_pod",
                            "cluster_alias": "docker-desktop",
                            "namespace": "payments",
                            "pod": {
                                "metadata": {
                                    "name": "payment-api-1",
                                    "namespace": "payments",
                                },
                                "status": {
                                    "conditions": [
                                        {
                                            "type": "Ready",
                                            "status": ready,
                                        },
                                    ],
                                },
                            },
                        },
                        error=None,
                        observed_at=datetime.now(timezone.utc),             # <- устанавливаем обязательно время создания наблюдения observation
                    ),
                ],
                current_state={},
            )



##########################################################
# Тестирование функции verifier_agent.verify_goal на отсутствие вызова LLM при проверке критериев Python 
##########################################################

# Тестовые параметры для функции make_input()
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ready", "goal_reached"),
    [
        ("True", True),
        ("False", False),
    ],
)

async def test_deterministic_goal_does_not_call_llm(    
    monkeypatch,
    ready,
    goal_reached,
):
    """
    Тестирование функции verifier_agent.verify_goal на отсутствие вызова LLM при проверке критериев Python 
    """

    # Иницализируем Mock
    fake_llm = AsyncMock(
        side_effect=AssertionError("LLM must not be called")
    )

    # Заменяем при вызове в модуле verifier_agent функцию verify_goal_with_llm на fake_llm
    monkeypatch.setattr(
        verifier_agent,
        "verify_goal_with_llm",
        fake_llm,
    )

    # Получаем объект GoalVerification и определяем достигнута ли ЦЕЛЬ
    result = await verifier_agent.verify_goal(
        make_input(ready, mixed=False)
    )

    # Тесты
    assert result.goal_reached == goal_reached

    fake_llm.assert_not_awaited()


##########################################################
# Тестирование функции verifier_agent.verify_goal 
##########################################################
@pytest.mark.asyncio
async def test_llm_success_does_not_override_python_failure(
    monkeypatch,
):
    """
    Тестирование функции verifier_agent.verify_goal() на корректность НЕ достижения ЦЕЛИ при условии
    - Критерий успешности принодлежщий LLM достигнут
    - Критерий успешности принодлежщий Python НЕ достигнут

    Python остаётся источником решения для закреплённых за ним критериев.
    """

    # Иницализируем Mock с достигнутым успешным критерием при надлежащим LLM
    fake_llm = AsyncMock(
        return_value=GoalVerification(
            goal_reached=True,
            satisfied_criteria=[RCA_CRITERION],
            missing_criteria=[],
            evidence=[
                "inspect-logs: обнаружена ошибка конфигурации",
            ],
            remaining_work=[],
            reason="Причина установлена",
        )
    )

    # Заменяем при вызове в модуле verifier_agent функцию verify_goal_with_llm на fake_llm
    monkeypatch.setattr(
        verifier_agent,
        "verify_goal_with_llm",
        fake_llm,
    )

    # Создаем объект с наблюдением который не покрывает READY_CRITERION
    verifier_input_object: VerifierInput = make_input(
            "False",                                # Указываем pod в status=False в наблюдении observation
            mixed=True,
        )

    
    # Получаем объект GoalVerification, определяем достигнута ли ЦЕЛЬ
    # на основе достижения критериев успешности принадлежащих LLM и Python 
    result = await verifier_agent.verify_goal(verifier_input_object)


    # Тесты
    assert result.goal_reached is False

    # Критерий успешности принодлежщий LLM достигнут
    assert result.satisfied_criteria == [RCA_CRITERION]

    # Критерий успешности принодлежщий Python НЕ достигнут
    assert result.missing_criteria == [READY_CRITERION]

    # Проверка вызова LLM не более одно раза
    fake_llm.assert_awaited_once()

    llm_input = fake_llm.call_args.args[0]

    # Проверка входного аргумента 
    assert llm_input.goal.success_criteria == [RCA_CRITERION]
    assert llm_input.goal.deterministic_rules == []