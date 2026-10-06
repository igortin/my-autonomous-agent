import json
from datetime import date, datetime
from typing import Any

from langchain_core.messages import ToolMessage

from sre_agent.state import ActionObservation

"""
Модуль переводит ответ конкретного инструмента (ToolMessage) в общий контракт ActionObservation.
"""


##########################################
# Helper функции
##########################################
def _json_default(value: Any) -> str:
    """
    Объекты datetime и date заменяются строками.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    raise TypeError(
        f"Unsupported result value: {type(value).__name__}"
    )

def _to_json_dict(payload: dict) -> dict[str, Any]:
    """
    Превращает dict в JSON строку и обратно.
    По пути datetime и date превращаются в ISO-строки.
    """
    
    # Превращает dict в JSON-строку.
    # helper функция _json_default() вызывается при необходимости для конвертации только неподдерживаемых значений, в том числе даты.
    serialized = json.dumps(
        payload,
        default=_json_default,
        ensure_ascii=False,
        allow_nan=False,
    )
    return json.loads(serialized)

##########################################
# Функция адаптер результатов
##########################################
def normalize_action_result(
    *,
    action_id: str,
    raw_result: Any,
) -> ActionObservation:
    """
    Адаптер результатов текущих Kubernetes tools.
    
    Инструменты возвращают результат в разном виде:
    - ToolMessage, 
    - JSON-строка 
    - dict

    Функция приводит любой из них к одному контракту:
        ActionObservation(
            action_id, 
            success, 
            result, 
            error,
        )

    ToolMessage создается после выполнения инструмента и содержит результат.    
    В ToolMessage есть поля: 
    1) content   - Результат инструмента, передаваемый LLM (str или list[str | dict]);
    2) artifact  - Дополнительный результат инструмента для кода приложения; не передаётся LLM как содержимое сообщения; (Any)
    3) status    - Статус выполнения инструмента (Literal["success", "error"]);
    """    
    tool_message_failed = False
    
    try:
        # Создаем переменную ссылающуюся на тот же python объект что и raw_result
        payload = raw_result

        
        """Если пришёл ToolMessage"""
        if isinstance(payload, ToolMessage):

            # Проверка статуса исполнения инструмента по ToolMessage.status
            tool_message_failed = (payload.status == "error")

            # Данные берутся из artifact, если там dict: это структурированный результат для кода. 
            # Иначе берётся content, то есть текст для LLM.
            if isinstance(payload.artifact, dict):
                payload = payload.artifact
            else:
                payload = payload.content

            # Особый случай: Ошибка выполения Tool возращенная в ToolMessage
            # tool_message_failed статус error и content содержит обычный текст, а не JSON.
            # Тогда функция сразу возвращает неуспешный результат, и этот текст в content становится полем error. 
            # Если текст пустой, ставится "Tool execution failed".
            if tool_message_failed and isinstance(payload, str):
                try:
                    # в content может лежать один из двух вариантов: JSON строка или просто строка
                    # пробуем разобрать строку как JSON строку и получить dict
                    payload = json.loads(payload)

                # Если payload была просто строка, то возниает JSONDecodeError 
                # и текст в content становится полем error
                except json.JSONDecodeError:
                    return ActionObservation(
                        action_id=action_id,
                        success=False,
                        result=None,
                        error=payload.strip()  or "Tool execution failed",
                    )

        """Если пришла JSON строка, просто строка или dict"""
        if isinstance(payload, str):
            # Десериализация payload.content строки в python объект dict
            payload = json.loads(payload)

        # Проверка десериализованного объекта тип данных dict
        if not isinstance(payload, dict):
            raise TypeError(
                "Expected a dictionary result"
            )

        # Проверка типа данных
        if type(payload.get("ok")) is not bool:
            raise ValueError(
                "Tool result must contain a boolean 'ok'"
            )
        

        """Определим успешность выполнения инструмента"""         
        
        # на основе ToolMessage, который содержит ключ "ок" (вернул Tool)
        success = (payload["ok"] and not tool_message_failed)

        # Из payload убираются ключи ok и error, остальное попадает в result.
        # Затем _to_json_dict прогоняет результат через json.dumps и обратно через json.loads
        # По пути datetime и date превращаются в ISO-строки.
        result = _to_json_dict({
            key: value
            for key, value in payload.items()
            if key not in {"ok", "error"}
        })


        """ Успешно выполенный Tool """
        if success:
            # Если в данных при этом есть непустой error, это ПРОТИВОРЕЧИЕ
            if payload.get("error") is not None:
                raise ValueError(
                    "Successful tool result contains an error"
                )

            return ActionObservation(
                action_id=action_id,
                success=True,
                result=result,
                error=None,
            )

        """ Сбой в выполенении Tool """
        # Отделить ошибку от результата.
        # читаем текст ошибки из ToolMessage, который содержит ключ "error" (вернул Tool)
        error = payload.get("error")

        # если error не str или пустая строка
        if not isinstance(error, str) or not error.strip():
            error = "Tool execution failed"    

        return ActionObservation(
            action_id=action_id,
            success=False,
            result=result or None,
            error=error,
        )

    except (TypeError, ValueError) as exc:
        return ActionObservation(
            action_id=action_id,
            success=False,
            result=None,
            error=f"Invalid tool result: {exc}",
        )



