from unittest.mock import AsyncMock, MagicMock

import pytest

import sre_agent.autonomy.executor as executor_module

from sre_agent.autonomy.duplicate_guard import (
    build_action_attempt,
    get_environment_fingerprint,
)
from sre_agent.autonomy.observer import (
    observer_node,
    route_after_observer,
)
from sre_agent.state import (
    ActionObservation,
    AgentAction,
    ExecutionPlan,
    PlanStep,
)
from sre_agent.tools.kubernetes import (
    GetDeploymentToolInput,
)







def make_action( action_id: str) -> AgentAction:
    """ 
    Вспомогательная функция инициализации Намерения действия.
    """
    return AgentAction(
        action_id=action_id,
        tool="get_deployment_tool",
        arguments={
            "cluster_alias": "docker-desktop",
            "namespace": "payments",
            "deployment_name": "payment-api",
        },
        expected_result=(
            "Получить текущее состояние Deployment"
        ),
        risk_level="read",
    )


def make_state(action: AgentAction) -> dict:
    """ 
    Вспомогательная функция инициализации SREAgentState.
    """
    # Создаем Шаг
    step = PlanStep(
        id="step-1",
        description="Прочитать состояние Deployment",
        agent="kubernetes",
        action_type="read",
        action=action,
        depends_on=[],
    )

    # Создаем план
    plan = ExecutionPlan(steps=[step])

    return {
        "execution_plan": plan.model_dump(mode="json"),
        "completed_step_ids": [],                       # Нет выполненныхь шагов
        "current_step": None,
        "pending_step_result": None,
        "execution_error": None,
        "iteration_count": 0,
        "observations": [],
        "action_history": [],                           # Нет наблюдений о состоянии Deployment
        "action_attempts": [],                          # Нет предыдущих попыток
        "human_escalation_required": False,
        "human_escalation_reason": None,
    }


# Создаем Mock иснтрумент
@pytest.fixture
def deployment_tool_mock(monkeypatch):
    """
    Функция Mock для вызова Tool
    """
    # MagicMock представляет объект инструмента.
    tool = MagicMock()

    # Настоящая схема аргументов.
    tool.args_schema = GetDeploymentToolInput

    # Вместо Kubernetes API — асинхронный AsyncMock позволяет сделать await tool.ainvoke() и проверить вызовы.
    tool.ainvoke = AsyncMock(
        return_value={
            "ok": True,
            "cluster_alias": "docker-desktop",
            "namespace": "payments",
            "deployment": {
                "metadata": {
                    "uid": "deployment-uid",
                    "generation": 5,
                },
                "spec": {
                    "replicas": 3,
                },
                "status": {
                    "observed_generation": 5,
                    "ready_replicas": 1,
                },
            },
        },
    )


    # Временно заменяем инструмент в реестре READ_ONLY_TOOL_REGISTRY 
    # в ключе get_deployment_tool значение на mock tool
    monkeypatch.setitem(
        executor_module.READ_ONLY_TOOL_REGISTRY,
        "get_deployment_tool",
        tool,
    )

    return tool


def make_attempt_record(
    action: AgentAction,
    action_history: list[dict],
) -> dict:
    """
    Функция создания попытки ActionAttempt.
    """
    validated_arguments = GetDeploymentToolInput.model_validate(action.arguments)
    
    normalized_arguments = validated_arguments.model_dump(mode="json")

    environment_fingerprint = get_environment_fingerprint(
            action=action,
            normalized_arguments=normalized_arguments,
            action_history=action_history,
            args_schema=GetDeploymentToolInput,
        )

    attempt = build_action_attempt(
        action=action,
        normalized_arguments=normalized_arguments,
        environment_fingerprint=environment_fingerprint,
    )

    return attempt.model_dump(mode="json")


########################################
# Тестирование executor_node
########################################
@pytest.mark.asyncio
async def test_executor_blocks_duplicate_before_tool_call(
    deployment_tool_mock,
):
    """
    Тестирование Executor node на вызов детерминированной проверки 
    ограничения количества попыток (ActionAttempt) до вызова Tool.
    """

    # Создаем намерение действия, которое executor должен выполнить.
    action = make_action("action-read-deployment")


    # Создаем состояние агента 
    state = make_state(action)

    # Предыдущая попытка той же операции при отсутствии известных наблюдений.
    previous_attempt = make_attempt_record(
        action=action,
        action_history=[],
    )

    # Лимит max_attempts=2 уже исчерпан.
    # Перезаписываем историю попыток в состоянии.
    state["action_attempts"] = [previous_attempt.copy(), previous_attempt.copy()]

    # Вызываем Executor и нода возвращает частичное обновление состояния.
    result = await executor_module.executor_node(state)

    # Доказывает, что метод не вызывали.
    # Поскольку детермирированное правило отработавает до вызова инструмента.
    deployment_tool_mock.ainvoke.assert_not_called()
    deployment_tool_mock.ainvoke.assert_not_awaited()


    # Первая блокировка — не ошибка: шаг пропущен, решает Verifier
    assert result["execution_error"] is None
    assert result["duplicate_blocked"] is True
    assert result.get("human_escalation_required") is not True
    assert result["pending_step_result"] is None
    assert result["current_step"] == "step-1"
    assert result["blocked_actions"][0]["duplicate_key"] == previous_attempt["duplicate_key"]

    # Нода возвращает обновления state.
    # Имитируем применение обновлений LangGraph.
    next_state = {**state, **result}

    # Заблокированная операция не стала третьей попыткой 
    # и состояние не изменилось после выполения Executor node. 
    assert next_state["action_attempts"] == state["action_attempts"]




@pytest.mark.asyncio
async def test_executor_records_attempt_when_tool_raises(
    deployment_tool_mock,
):
    """
    Тестирование Executor node - если инструмент начал выполняться и завершился ошибкой, попытка всё равно была..
    """
        
    action = make_action("action-read-deployment")
    
    state = make_state(action)

    deployment_tool_mock.ainvoke.side_effect = RuntimeError("Kubernetes API unavailable")

    result = await executor_module.executor_node(state)

    assert len(result["action_attempts"]) == 1

    observation = ActionObservation.model_validate(result["pending_step_result"]["observation"])

    assert observation.success is False

    assert observation.result is None

    assert "Kubernetes API unavailable" in observation.error

    # В твоём executor исключение инструмента превращается в неуспешное действие в наблюдении.
    assert result["execution_error"] is None



@pytest.mark.asyncio
async def test_new_action_id_does_not_bypass_duplicate_guard(
    deployment_tool_mock,
):
    """
    Тестированеи Executor что новый action_id не обходит лимит 
    и детеврминированное правло ограничвает выполнение Tool еще до вызова.
    LLM при перепланировании может создать новый ID для той же операции.
    """
    
    previous_action = make_action(
        action_id="old-action",
    )

    previous_attempt = make_attempt_record(
        action=previous_action,
        action_history=[],
    )


    current_action = make_action(
        action_id="new-action",
    )

    state = make_state(current_action)


    state["action_attempts"] = [previous_attempt.copy(), previous_attempt.copy()]

    result = await executor_module.executor_node(state)

    deployment_tool_mock.ainvoke.assert_not_called()

    assert result["duplicate_blocked"] is True
