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
# Unit tests 1
###############################################
def test_successful_tool_result_is_normalized():
    """
    Тестирование правильного преобразования результата.
    
    Нормализация и создание ActionObservation, 
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
# Unit tests 2
###############################################
def test_failed_tool_result_preserves_error_details():
    """
    Тестирование сохранения деталей ошибки.
    
    Создание ActionObservation,
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
# Unit tests 3
###############################################
def test_tool_message_is_correct():
    """
    Тестирование удаления транспортной оболочки

    Создание ActionObservation при получении ToolMessage 
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
# Unit tests 4
###############################################
def test_tool_message_error_overrides_payload_success():
    """
    Тестирование удаления транспортной оболочки

    Cоздание ActionObservation при получении ToolMessage 
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
# Unit tests 5
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
    Тестирование отклонения некорректного статуса.

    Создание ActionObservation при получении не корректного результата выполнении Tool. 
    """

    observation = normalize_action_result(
        action_id="read-pod-status",
        raw_result=raw_result,
    )

    assert observation.success is False
    assert observation.error.startswith("Invalid tool result:")


###############################################
# Unit tests 6
###############################################
def test_datetime_becomes_json_serializable():
    """
    Тестирование пригодность результата для JSON.
    
    Cоздание ActionObservation при получении корректного результата выполнении Tool с datetime. 
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
# Unit tests 7
###############################################
def test_success_with_error_is_rejected():
    """
    Тестирование запрета противоречивого observation.

    Создание ActionObservation при ПРОТИВОРЕЧИИ в результате выполнении Tool.
    (success=True и error="не пустой")
    """
    with pytest.raises(ValidationError):
        ActionObservation(
            action_id="read-pod-status",
            success=True,
            result={},
            error="Connection refused",
        )