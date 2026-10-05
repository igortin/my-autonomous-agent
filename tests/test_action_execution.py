import asyncio
import logging

from unittest.mock import AsyncMock
import pytest

from pydantic import BaseModel, ConfigDict
from sre_agent.autonomy import executor

#  Определяем фейк схему аргументов
class FakePodInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_alias: str
    namespace: str
    pod_name: str

#######################################
#  Подготовка к тестированию
#######################################
@pytest.fixture
def action_state():
    return {
        "iteration_count": 0,
        "completed_step_ids": [],
        "execution_plan": {
            "steps": [
                {
                    "id": "inspect-pod",
                    "description": "Inspect pod",
                    "agent": "kubernetes",
                    "action_type": "read",
                    "action": {
                        "action_id": "read-pod-status",
                        "tool": "get_pod_tool",
                        "arguments": {
                            "cluster_alias": "test-cluster",
                            "namespace": "payments",
                            "pod_name": "payment-api-1",
                        },
                        "expected_result": "Obtain pod status.",
                        "risk_level": "read",
                    },
                    "depends_on": [],
                }
            ]
        },
    }

#######################################
#  Unit-test 1
#######################################
def test_action_is_logged_before_tool_call(
    monkeypatch,
    caplog,
    action_state,
):
    """
    Тестирование Executor логирует `Намерение` перед вызовом Tool
    """
    # настройка логирования
    caplog.set_level(logging.INFO, logger=executor.__name__)

    # Фиктивная функция
    async def fake_invoke(arguments): 
        
        """
        Функция проверяет лог Executor 
        на наличие записи об атрибутах указанных в fixture функции action_state() 
        """    

        # This assertion runs INSIDE the tool invocation.    
        # The log must already exist at this point.
        records = [
            record
            for record in caplog.records
            if record.name == executor.__name__ and "agent_action_before_execution" in record.getMessage()
        ]

        assert len(records) == 1

        message = records[0].getMessage()

        # Проверка в записи лога значений атрибутов указанных в action_state()
        assert "read-pod-status" in message

        assert "get_pod_tool" in message

        assert "Obtain pod status." in message

        return {
            "ok": True,
            "pod": {"phase": "Running"},
        }

    # Устаналиваем mock
    fake_tool = AsyncMock()

    # Устаналиваем схему аргументов
    fake_tool.args_schema = FakePodInput

    # при вызове .ainvoke(...) выполнить функцию fake_invoke с теми же аргументами.
    fake_tool.ainvoke.side_effect = fake_invoke

    # Подменим в модуле Executor в реестре 
    # READ_ONLY_TOOL_REGISTRY инструмент
    #  get_pod_tool на fake_tool
    monkeypatch.setattr(
        executor,
        "READ_ONLY_TOOL_REGISTRY",
        {"get_pod_tool": fake_tool},
    )

    # Вызываем Executor 
    result = asyncio.run(
        executor.executor_node(action_state)
    )

    # Тест
    assert result["execution_error"] is None

    # Проверяем что Executor вызывал fake_tool с аргументами
    fake_tool.ainvoke.assert_awaited_once_with(
        {
            "cluster_alias": "test-cluster",
            "namespace": "payments",
            "pod_name": "payment-api-1",
        }
    )

#######################################
#  Unit-test 2
#######################################
@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("risk_level", "high", "forbidden_risk_level"),
        ("tool", "delete_pod_tool", "tool_not_allowed"),
    ],
)
def test_forbidden_action_never_calls_tool(
    monkeypatch,
    action_state,
    field,
    value,
    expected_error,
):
    """
    Тестирование Executor на обработку ошибок 
    при не корректном значении risk_level и tool 
    в dict action_state.
    """ 
    
    # Создаем переменную action которая ссылается на dict в action_state
    action = action_state["execution_plan"]["steps"][0]["action"]

    # ЗАМЕНИМ значения для существующих полей в блоке dict из parametrize
    action[field] = value

    # Устаналиваем mock
    fake_tool = AsyncMock()

    # Устаналиваем схему аргументов
    fake_tool.args_schema = FakePodInput

    # Подменим в модуле executor в ресстре READ_ONLY_TOOL_REGISTRY инструмент get_pod_tool на fake_tool
    monkeypatch.setattr(
        executor,
        "READ_ONLY_TOOL_REGISTRY",
        {"get_pod_tool": fake_tool},
    )


    # Вызываем Executor и передаем обновленный dict action_state 
    result = asyncio.run(
        executor.executor_node(action_state)
    )

    # Тесты на expected_error 

    # Тест 1 - forbidden_risk_level
    # Тест 2 - tool_not_allowed
    assert result["execution_error"]["type"] == expected_error
    
    fake_tool.ainvoke.assert_not_awaited()



#######################################
#  Unit-test 3
#######################################
def test_invalid_arguments_never_call_tool(
    monkeypatch,
    action_state,
):
    """
    Тестирование создания execution_plan на ноде Executor при не корректных аргументах в AgentAction 
    """

    # Создание переменной ссылающейся на блок dict в action_state
    action = action_state["execution_plan"]["steps"][0]["action"]

    # Удаление ключ:занчение в переменной ссылающейся на блок dict в action_state
    del action["arguments"]["cluster_alias"]


    # Установка mock
    fake_tool = AsyncMock()

    # установка схемы аргументов на фейк класс
    fake_tool.args_schema = FakePodInput

    # Замена в модуле executor в реестре READ_ONLY_TOOL_REGISTRY инструмента get_pod_tool на fake_tool
    monkeypatch.setattr(
        executor,
        "READ_ONLY_TOOL_REGISTRY",
        {"get_pod_tool": fake_tool},
    )

    # Вызов Executor с некорректным action_state для вызова интсрумента 
    result = asyncio.run(executor.executor_node(action_state))

    # ТЕСТЫ
    assert result["execution_error"]["type"] == "invalid_tool_args"

    # Проверка асинхронный метод ainvoke ни разу не был выполнен через await
    fake_tool.ainvoke.assert_not_awaited()


#######################################
#  Unit-test 4
#######################################
def test_action_log_survives_tool_exception(
        monkeypatch,
        caplog,
        action_state,
):
    """
    Тестирование создания записи в лог на ноде Executor при не корректном tool_name в AgentAction 
    """

    # Настройка логера
    caplog.set_level(logging.INFO, logger=executor.__name__)

    # Установка Mock
    fake_tool = AsyncMock()

    # Установка схемы аргументов
    fake_tool.args_schema = FakePodInput

    # При вызове ainvoke вернуть исключение
    fake_tool.ainvoke.side_effect = RuntimeError("Kubernetes API unavailable")


    # Замена в модуле executor в реестре READ_ONLY_TOOL_REGISTRY инструмента get_pod_tool на fake_tool
    monkeypatch.setattr(
        executor,
        "READ_ONLY_TOOL_REGISTRY",
        {"get_pod_tool": fake_tool},
    )

    # Вызов Executor
    result = asyncio.run(
        executor.executor_node(action_state)
    )

    # Тесты
    assert result["execution_error"]["type"] == "executor_error"

    assert "read-pod-status" in caplog.text

    # Проверка асинхронный метод ainvoke ни разу не был выполнен через await
    fake_tool.ainvoke.assert_awaited_once()