import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from sre_agent.agents import verifier_agent
from sre_agent.state import (
    AgentGoal,
    ActionObservation,
    GoalVerification,
    VerifierInput,
)



###################################
# Подготовка тестовых данных
####################################
@pytest.fixture
def verifier_input():
    return VerifierInput(
        goal=AgentGoal(
            description="Проверить готовность payment-api-1",
            success_criteria=[
                "Pod payment-api-1 имеет Ready=True"
            ],
            constraints=["Read-only"],
            max_iterations=3,
        ),
        observations=[
            ActionObservation(
                action_id="inspect-pod",
                success=True,
                result={
                    "pod_name": "payment-api-1",
                    "ready": False,                                             # <- искусственный формат для unit-теста, а не утверждение о реальном payload твоего Kubernetes tool
                },
                error=None,
            )
        ],
        current_state={
            "iteration_count": 0,
            "max_iterations": 3,
        },
    )

def test_reached_goal_requires_evidence():
    """
    Тестирование на наличие обязательно подтверждений для достижения цели 
    иначе поднимается исключение (Противоречие).
    """

    # определяем в аргументе match проверяемый Regex pattern
    with pytest.raises(ValidationError,  match="evidence"):
        GoalVerification(
            goal_reached=True,
            satisfied_criteria=["Pod Ready=True"],
            missing_criteria=[],
            evidence=[],                                    # <- не указываем доказательства что успешно цель достигнута
            remaining_work=[],
            reason="Цель достигнута",
        )





def test_reached_goal_cannot_have_remaining_work():
    """
    Тестирование на обязательное отсуствие remainig_work при достижении цели 
    иначе поднимается исключение (Противоречие).
    """

    # определяем в аргументе match проверяемый Regex pattern
    with pytest.raises(ValidationError,  match="remaining work"):
        GoalVerification(
            goal_reached=True,
            satisfied_criteria=["Pod Ready=True"],
            missing_criteria=[],
            evidence=["inspect-pod: ready=True"],                                    
            remaining_work=["Проверить Pod лог"],          # <- указываем действие
            reason="Цель достигнута",
        )

# Передаем тестовый объект класса VerifierInput в аргументе 
def test_verifier_cannot_omit_criterion(verifier_input):
    """
    Тестирование на создание исключения 
    при decision решении, что цель успешно достигнута, 
    но список не содержит успешно достигнутых критериев.
    
    Возникает ПРОТИВОРЕЧИЕ поскольку в 
    verifier_input.goal.satisfied_criteria 
    сушествует критерий, который не достигнут.   
    """


    # Фейк решение по достижению цели
    decision = GoalVerification(
        goal_reached=True,
        satisfied_criteria=[],                             # <- указываем пустое значение успешно достигнутых критериев  
        missing_criteria=[],
        evidence=["inspect-pod: инструмент выполнен"],
        remaining_work=[],
        reason="Проверка завершена",
    )

    # Проверим согласованность решения объекта decision с исходной целью.
    # определяем в аргументе match проверяемый Regex pattern по тексту ошибки
    with pytest.raises(ValueError, match="omitted"):
        verifier_agent.validate_verification(
            verifier_input,
            decision
        )



def test_reached_goal_requires_observation(verifier_input):
    """
    Тестирование на обязательного наличие observations (результатов шагов)
    при успешном достижении цели. 
    """
    
    # обнуляем результатов шагов в тестовых данных с целю вызвать исключение на validate_verification()
    verifier_input.observations = []

    # Фейк решение
    decision = GoalVerification(
        goal_reached=True,
        satisfied_criteria=(
            verifier_input.goal.success_criteria
        ),
        missing_criteria=[],
        evidence=["Предполагается, что Pod готов"],
        remaining_work=[],
        reason="Цель достигнута",
    )

    # Проверим согласованность решения объекта decision с исходной целью.
    with pytest.raises(ValueError, match="successful observation"):
        verifier_agent.validate_verification(
            verifier_input,
            decision,
        )



@pytest.mark.asyncio
async def test_real_llm_successful_tool_can_leave_goal_unreached(
    monkeypatch,
    verifier_input,
):
    """
    Тестирование - Verifier может вернуть отрицательное решение при успешном tool call.
    """
    
    # Читаем первый критерий успешности который должен быть достигнут
    criterion = verifier_input.goal.success_criteria[0]

    # Фейк решение по достижению цели
    decision = GoalVerification(
        goal_reached=False,
        satisfied_criteria=[],
        missing_criteria=[criterion],               # <- указываем пропущенный критерий
        evidence=[
            "inspect-pod: result.ready=False"       
        ],
        remaining_work=[
            "Получить дополнительные сведения "
            "о причине неготовности Pod"
        ],
        reason=(
            "Инструмент успешно прочитал Pod, "
            "но Pod не готов"
        ),
    )

    # Инициализируем Mock
    fake_model = MagicMock()
    # При вызоыве возращаем тестовое решение
    fake_model.ainvoke = AsyncMock(
        return_value=decision
    )

    # заменяем в модуле verifier_agent объект verifier_model на fake_model
    monkeypatch.setattr(
        verifier_agent,
        "verifier_model",
        fake_model,
    )

    # Вызываем verifier_model в функции путем подмены с fake_model   
    result = await verifier_agent.verify_goal(
        verifier_input,
    )


    # Тесты 
    assert result.goal_reached is False

    # Проверка что был одиночный вызов
    fake_model.ainvoke.assert_awaited_once()

    # Читаем первый аргумент при вызове LLM
    messages = fake_model.ainvoke.call_args.args[0]

    # Читаем атрибут из аргумента
    payload = json.loads(messages[1].content)

    # Проверяем успешное выполнение Tool из первого аргумента (verifier_input)
    assert payload["observations"][0]["success"] is True

    # Проверяем что в observation шага Pod (см. verifier_input)
    assert payload["observations"][0]["result"]["ready"] is False

    # Проверяем ключ success_criteria в первом аргументе, 
    # поскольку ключ:значение добавляется в аргумент на verify_goal
    assert payload["success_criteria"] == [criterion]

    # Проверяем максимальное количество итераций lifecycle
    assert payload["current_state"]["max_iterations"] == 3    