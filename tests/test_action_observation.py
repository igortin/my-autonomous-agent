import json
from datetime import datetime, timezone

import pytest
from langchain_core.messages import ToolMessage

from pydantic import ValidationError

from sre_agent.autonomy.observation import (
    normalize_action_result,
)
from sre_agent.state import ActionObservation




###############################################
# Unit tests - Тестирование правильного преобразования результата.
###############################################
def test_successful_tool_result_is_normalized():
    """   
    Тестирование нормализации и создание ActionObservation, 
    при получении dict как результат выполненного Tool.
    """
    # Создание и валидация результатов выполнения инструмента 
    observation = normalize_action_result(
        action_id="read-pod-status",
        raw_result={
            "ok": True,
            "cluster_alias": "test-cluster",
            "pod": {
                "status": {
                    "phase": "Running",
                },
            },
        },
    )

    # Тесты
    assert observation.action_id == "read-pod-status"
    # значение записыватся из raw_result["ok"]
    assert observation.success is True

    assert observation.error == None
    assert observation.result["pod"]["status"]["phase"] == "Running"
    assert "ok" not in observation.result


###############################################
# Unit tests - Тестирование сохранения деталей ошибки.
###############################################
def test_failed_tool_result_preserves_error_details():
    """   
    Тестирование создания ActionObservation,
    при получении dict как результат выполненного Tool,
    с сохранением деталей ошибки в result.
    """
    observation = normalize_action_result(
        action_id="read-pod-status",
        raw_result={
            "ok": False,
            "error": "Kubernetes API error",
            "status": 403,
            "reason": "Forbidden",
        },
    )

    # значение записыватся из raw_result["ok"]
    assert observation.success is False
    assert observation.error == "Kubernetes API error"

    # в функции normalize_action_result 
    # из payload убираются ключи 'ok' и 'error',
    # остальное попадает в result.
    assert observation.result == {
            "status": 403,
            "reason": "Forbidden",
    }


###############################################
# Unit tests - Тестирование удаления транспортной оболочки
###############################################
def test_tool_message_is_correct():
    """
    Тестирование создания ActionObservation при получении ToolMessage 
    и уcпешном выполнении Tool.
    """
    # Определим ToolMessage
    message = ToolMessage(
        tool_call_id="transport-call-1",
        content=json.dumps({
            "ok": True,
            "events": [
                {"reason": "BackOff"}
            ],
        }),
    )

    # в функции normalize_action_result 
    # из payload убираются ключи 'ok' и 'error',
    # остальное попадает в result.
    observation = normalize_action_result(
        action_id="read-events",
        raw_result=message,
    )

    assert observation.action_id == "read-events"
    assert observation.success is True
    assert observation.result == {
        "events": [{"reason": "BackOff"}],
    }
    assert "tool_call_id" not in observation.model_dump()


###############################################
# Unit tests - Тестирование удаления транспортной оболочки ToolMessage
###############################################
def test_tool_message_error_overrides_payload_success():
    """
    Тестирование создания ActionObservation при получении ToolMessage 
    и сбое выполнении Tool. 
    """
    # Определим ToolMessage
    message = ToolMessage(
        tool_call_id="transport-call-1",
        status="error",
        content=json.dumps({
            "ok": True,
            "pod": {},
        }),
    )
    
    # в функции normalize_action_result 
    # из payload убираются ключи 'ok' и 'error',
    # остальное попадает в result.
    observation = normalize_action_result(
        action_id="read-pod-status",
        raw_result=message,
    )

    assert observation.success is False
    assert observation.error is not None

###############################################
# Unit tests - Тестирование удаления транспортной оболочки ToolMessage
###############################################
@pytest.mark.parametrize(
    "raw_result",
    [
        None,
        [],
        "not-json",
        {},
        {"ok": "false"},
    ],
)

def test_invalid_result_does_not_become_success(raw_result):
    """
    Создание ActionObservation при получении не корректного результата выполнении Tool. 
    """

    observation = normalize_action_result(
        action_id="read-pod-status",
        raw_result=raw_result,
    )

    assert observation.success is False
    assert observation.error.startswith("Invalid tool result:")


###############################################
# Unit test - Тестирование пригодность результата с datetime для JSON.
###############################################
def test_datetime_becomes_json_serializable():
    """   
    Тестирование создания ActionObservation при получении dict 
    как корректного результата выполненного Tool 
    с datetime. 
    """
    # Создание объекта класса ActionObservation 
    # c использованием сериализцаии datetime в строку IsoFormat
    observation = normalize_action_result(
        action_id="read-pod-status",
        raw_result={
            "ok": True,
            "created_at": datetime(
                2026, 10, 5, tzinfo=timezone.utc
            ),
        },
    )

    # Проверка IsoFormat
    assert observation.result["created_at"] == "2026-10-05T00:00:00+00:00"

    # Проверка сериализации объекта в dict и потом в строку
    json.dumps(observation.model_dump(mode="json"))


###############################################
# Unit tests - Тестирование возникновения ошибки при противоречии в результате выпонения Tool.
###############################################
def test_success_with_error_is_rejected():
    """
    Тестирование создания ActionObservation при получении dict 
    c ПРОТИВОРЕЧИЯМИ в результате выполнении Tool.
    (success=True и error="не пустой")
    """
    with pytest.raises(ValidationError):
        ActionObservation(
            action_id="read-pod-status",
            success=True,
            result={},
            error="Connection refused",
        )