import hashlib
import json
from typing import Any

from sre_agent.state import (
    ActionAttempt,
    ActionObservation,
    AgentAction,
)







###########################################
# Вспомогательная функция sha256 хеширования
###########################################
def stable_hash(value: Any) -> str:
    
    serialized = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()




###########################################
# Вспомогательная функция создания отпечатка
###########################################
def build_action_fingerprint(
    action: AgentAction,
    normalized_arguments: dict[str, Any],
) -> str:
    """
    Функция создает хеш значение описания попытки вызова инстурмента
    """
    return stable_hash(
        {
            "tool": action.tool,
            "arguments": normalized_arguments,
        }
    )




###########################################
# Вспомогательная функция создания Deployment представления
###########################################
def deployment_state_projection(result: dict[str, Any],) -> dict[str, Any] | None:
    """
    Вспомогателльная функция формирования представления Deployment.
    Тоетсь описания состояния ресурса.
    """    
    # Читаем бизнес данные по ресурсу
    deployment = result.get("deployment")

    if not isinstance(deployment, dict):
        return None

    # Получааем данные из блоков
    metadata = deployment.get("metadata") or {}
    spec = deployment.get("spec") or {}
    status = deployment.get("status") or {}

    # Проврека типа данных
    if not all(
        isinstance(section, dict)
        for section in (metadata, spec, status)
    ):            
        return None


    # Читаем уникальный идентификатор ресурса
    uid = metadata.get("uid")

    if not isinstance(uid, str) or not uid:
        return None

    return {
        "kind": "deployment",
        "uid": uid,
        "generation": metadata.get("generation"),
        "observed_generation": status.get("observed_generation"),
        "desired_replicas": spec.get("replicas"),
        "ready_replicas": status.get("ready_replicas") or 0,
        "updated_replicas": status.get("updated_replicas") or 0,
        "available_replicas": status.get("available_replicas") or 0,
    }



###########################################
# Вспомогательная функция создания отпечатка состояния ресурса Deployment
###########################################
def get_environment_fingerprint(
    *,
    action: AgentAction,
    normalized_arguments: dict[str, Any],
    action_history: list[dict[str, Any]],
    args_schema: Any,
) -> str:
    """
    Вспомогательнная функция создания отпечатка состояния Deployment по fingerprint (описания попытки вызова инстурмента), 
    который содержит вызов инструмента get_deployment_tool.
    """

    # Создаем отпечаток попытки
    action_fingerprint = build_action_fingerprint(
        action,
        normalized_arguments,
    )

    # Итерируемся по наблюдениям от новых записей к старым из списка trajectory
    for raw in reversed(action_history):
        
        # Валидируем и создаем обьект наблюдение
        observation = ActionObservation.model_validate(raw)

        # Получаем из наблюдения выполненное действие класса AgentAction
        previous_action = observation.action

        if previous_action is None:
            # Пропускаем и переходим к следующему наблюдению
            continue

        # Если наблюдение не содержит такой же Tool
        if previous_action.tool != action.tool:
            # Пропускаем и переходим к следующему наблюдению
            continue

        #  Валидируем обьект args_schema и сериализуем в JSON
        previous_arguments = args_schema.model_validate(previous_action.arguments).model_dump(mode="json")

        # Создаем отпечаток Предыдущей попытки
        previous_fingerprint = build_action_fingerprint(
            previous_action,
            previous_arguments,
        )

        # Сравниваем хеш отпечатков
        if previous_fingerprint != action_fingerprint:
            # Пропускаем и переходим к следующему наблюдению
            continue

        # Проверяем на успешность выполнения шага
        if not observation.success:
            # Пропускаем и переходим к следующему наблюдению
            continue


        if action.tool == "get_deployment_tool":

            # Создаем Deployment представление
            projection = deployment_state_projection(observation.result)

            # Хеширование Deployment представления
            if projection is not None:
                return stable_hash(projection)

    
    
    
    # Возращаем в случае исключений
    return stable_hash(
        {
            "state": "unknown",
            "action_fingerprint": action_fingerprint,
        }
    )


############################################
# Вспомогательная функция создания обьекта Попытки вызова инструментов
############################################
def build_action_attempt(
    *,
    action: AgentAction,
    normalized_arguments: dict[str, Any],
    environment_fingerprint: str,
) -> ActionAttempt:
    """
    Функция создания Поптыток вызова инструментов.
    """

    action_fingerprint = build_action_fingerprint(
        action,
        normalized_arguments,
    )

    duplicate_key = stable_hash(
        {
            "action": action_fingerprint,
            "environment": environment_fingerprint,
        }
    )

    return ActionAttempt(
        action_id=action.action_id,
        action_fingerprint=action_fingerprint,
        environment_fingerprint=environment_fingerprint,
        duplicate_key=duplicate_key,
    )



############################################
# Вспомогательная функция проверки Количества попыток вызова инструментов
############################################
def is_duplicate_limit_reached(
    *,
    candidate: ActionAttempt,
    attempts: list[dict[str, Any]],
    max_attempts: int,
) -> bool:
    """
    Функция ограничения количества попыток вызова инструментов.
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")

    matching_count = 0

    # Итериремуся по списку обьектов класса ActionAttempt   
    for raw in attempts:

        # Валидация и создание обьекта ActionAttempt
        attempt = ActionAttempt.model_validate(raw)

        # Сравнение ключа дубликации
        if attempt.duplicate_key == candidate.duplicate_key:
            matching_count += 1

    return matching_count >= max_attempts