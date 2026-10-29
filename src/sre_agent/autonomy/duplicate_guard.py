import hashlib
import json

from sre_agent.state import (
    ActionAttempt,
    ActionObservation,
    AgentAction,
)

from typing import Any, Callable



# Сколько раз одинаковый вызов разрешён при одном и том же состоянии среды
MAX_DUPLICATE_ATTEMPTS = 2


###########################################
# Функция создания представления Deployment состояния (get_deployment_tool)
###########################################
def deployment_state_projection(result: dict[str, Any],) -> dict[str, Any] | None:
    """
    Вспомогательная функция создания представления одного Deployment.
    Тоетсь описания состояния ресурса.
    """    
    # Читаем deployment.to_dict() из входного результата get_deployment_tool
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
# Вспомогательная функция представления состояния контейнера в pod
###########################################
def _container_state_projection(container_status: dict[str, Any]) -> dict[str, Any]:
    """
    Вспомогательная функция создания представления одного контейнера.

    Сжимает state и last_state контейнера до вида состояния 
    и причины без timestamps.
    """
    
    def _state_kind(state: dict[str, Any] | None) -> dict[str, Any] | None:
        """
        Внутренняя функция получения данных по container
        - '.status.containerStatuses.[].lastState'
        - '.status.containerStatuses.[].state'
        """
        # Провереям тип данных 
        if not isinstance(state, dict):
            return None

        # В to_dict() заполнен ровно один из ключей running/waiting/terminated
        for kind in ("running", "waiting", "terminated"):
            
            # Читаем данные на каждый статус running/waiting/terminated
            details = state.get(kind)

            if isinstance(details, dict):
                return {
                    "kind": kind,
                    "reason": details.get("reason"),
                    "exit_code": details.get("exit_code"),
                }
        return None

    # Выводим представление состояния контейнеров в pod
    return {
        "name": container_status.get("name"),
        "ready": container_status.get("ready"),
        "started": container_status.get("started"),
        "restart_count": container_status.get("restart_count") or 0,
        "state": _state_kind(container_status.get("state")),
        "last_state": _state_kind(container_status.get("last_state")),
    }


###########################################
# Функция создания Pod представления (get_pod_tool)
###########################################
def pod_state_projection(result: dict[str, Any]) -> dict[str, Any] | None:
    """
    Функция создания представления одной поды из данных 
    полученных инструментом get_pod_tool.
    """
    # Читаем состояние pod.to_dict() из входного результата get_pod_tool
    pod = result.get("pod")

    if not isinstance(pod, dict):
        return None

    metadata = pod.get("metadata") or {}

    status = pod.get("status") or {}

    # Читаем pod uid 
    uid = metadata.get("uid")

    if not isinstance(uid, str) or not uid:
        return None

    # Выводим представление состояния pod-ы
    return {
        "kind": "pod",
        "uid": uid,
        "phase": status.get("phase"),
        # Создаем список всех состояний этой поды 
        # из множеств только type/status 
        # - '.status.conditions'
        "conditions": sorted(
            (c.get("type"), c.get("status")) for c in (status.get("conditions") or [])
        ),
        # Создаем список из Представлений состояний контейнеров одной поды 
        # - '.status.containerStatuses'
        "containers": sorted(
            (_container_state_projection(cs) for cs in (status.get("container_statuses") or [])),
            key=lambda item: item["name"] or "",
        ),
    }



###########################################
# Функция создания представления списка Pod-ов (list_pods_tool)
###########################################
def pod_list_state_projection(result: dict[str, Any]) -> dict[str, Any] | None:
    """
    Функция создания представления списка подов из данных 
    полученных инструментом list_pods_tool.
    """

    # Читаем состояние pods из входного из входного результата list_pods_tool
    pods = result.get("pods")

    if not isinstance(pods, list):
        return None

    # Выводим представление состояния списка pods
    return {
        "kind": "pod_list",
        "pods": sorted(
            (
                pod.get("name"),
                pod.get("phase"),
                pod.get("node"),
                pod.get("restart_count") or 0,
            )
            for pod in pods
            if isinstance(pod, dict)
        ),
    }


###########################################
# Функция создания представления событий (get_pod_events_tool, get_node_events_tool)
###########################################
def events_state_projection(result: dict[str, Any]) -> dict[str, Any] | None:
    """
    Функция создания представления списка ивентов из данных 
    полученных инструментом get_pod_events.
    """
    # Читаем все ивенты из входного результата get_pod_events_tool
    events = result.get("events")

    if not isinstance(events, list):
        return None

    # Выводим представление состояния списка ивентов
    # count растёт при каждом повторении события — это и есть изменение среды
    return {
        "kind": "events",
        "events": sorted(
            (
                event.get("type"),
                event.get("reason"),
                event.get("message"),
                event.get("count") or 0,
            )
            for event in events if isinstance(event, dict)
        ),
    }


###########################################
# Функция создания представления логов (get_pod_logs_tool)
###########################################
def logs_state_projection(result: dict[str, Any]) -> dict[str, Any] | None:
    """
    Функция создания представления списка логов из данных 
    полученных инструментом get_pod_logs.
    """

    # Читаем все логи из входного результата get_pod_logs_tool
    logs = result.get("logs")

    if not isinstance(logs, str):
        return None

    # Выводим представление состояния логов в хеш строке
    # Логи читаются с timestamps=True: любая новая строка меняет хеш
    return {
        "kind": "logs",
        "logs_hash": stable_hash(logs),
    }


###########################################
# Вспомогательная функция создания представления Node
###########################################
def _node_conditions(conditions: list[Any] | None) -> list[tuple]:
    """
    Вспомогательная функция создания списка множеств состояний k8s Node 
    - .status.conditions
    """
    return sorted(
        (
            c.get("type"), 
            c.get("status"), 
            c.get("reason")
        )
        for c in (conditions or []) if isinstance(c, dict)
    )

###########################################
# Функция создания представления Node (get_node_tool)
###########################################
def node_state_projection(result: dict[str, Any]) -> dict[str, Any] | None:
    """
    Функция создания представления состояния k8s Node из данных 
    полученных инструментом get_node_tool
    """

    # Читаем node.to_dict() из входного результата get_node_tool
    node = result.get("node")

    if not isinstance(node, dict):
        return None

    metadata = node.get("metadata") or {}

    spec = node.get("spec") or {}

    status = node.get("status") or {}

    # Читаем node uid 
    uid = metadata.get("uid")

    if not isinstance(uid, str) or not uid:
        return None

    # Выводим представление состояния ноды
    return {
        "kind": "node",
        "uid": uid,
        "unschedulable": bool(spec.get("unschedulable")),
        "conditions": _node_conditions(status.get("conditions")),
    }

###########################################
# Функция создания представления списка Nodeы (list_nodes_tool)
###########################################
def node_list_state_projection(result: dict[str, Any]) -> dict[str, Any] | None:
    """
    Функция создания представления списка состояний k8s Nodes из данных 
    полученных инструментом list_nodes_tool
    """

     # Читаем все ноды из входного результата list_node_tool
    nodes = result.get("nodes")

    if not isinstance(nodes, list):
        return None

    # Выводим представление состояния списка нод
    return {
        "kind": "node_list",
        "nodes": sorted(
            (node.get("name"), _node_conditions(node.get("conditions")))
            for node in nodes if isinstance(node, dict)
        ),
    }


###########################################
# Вспомогательная функция sha256 хеширования
###########################################
def stable_hash(value: Any) -> str:
    # Сериализация обьекта dict в строку json
    serialized = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )

    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


###########################################
# Функция создания Отпечатка попытки вызова инструмента
###########################################
def build_action_fingerprint(
    action: AgentAction,
    normalized_arguments: dict[str, Any],
) -> str:
    """
    Вспомогательная функция создания Отпечатка Попытки вызова инстурмента
    """
    return stable_hash(
        {
            "tool": action.tool,
            "arguments": normalized_arguments,
        }
    )


###########################################
# Функции создания Представления собраны в реестр STATE_PROJECTIONS
###########################################
STATE_PROJECTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]] = {
    "get_deployment_tool": deployment_state_projection,
    "get_pod_tool": pod_state_projection,
    "list_pods_tool": pod_list_state_projection,
    "get_pod_events_tool": events_state_projection,
    "get_node_events_tool": events_state_projection,
    "get_pod_logs_tool": logs_state_projection,
    "get_node_tool": node_state_projection,
    "list_nodes_tool": node_list_state_projection,
}

###########################################
# Функция создания Отпечатка состояния ресурса
###########################################
def get_environment_fingerprint(
    *,
    action: AgentAction,
    normalized_arguments: dict[str, Any],
    action_history: list[dict[str, Any]],
    args_schema: Any,
) -> str:
    """
    Функция определения в каком состоянии был ресурс, 
    когда агент последний раз успешно выполнял точно такое же действие 
    вызов идентичного инструмента. 
    
    Ответ возвращается строкой-хэшем.
    """

    # Создаем отпечаток попытки на основе входных данных
    action_fingerprint = build_action_fingerprint(
        action,
        normalized_arguments,
    )

    # Итерируемся по наблюдениям от новых записей к более старым в списке trajectory
    for raw in reversed(action_history):
        
        # Валидируем и создаем обьект предыдущего Наблюдения из списка истории наблюдений
        previous_observation = ActionObservation.model_validate(raw)

        # Получаем из очередного предыдущего наблюдения выполненное НЕМЕРЕНИЕ действие класса AgentAction
        previous_action = previous_observation.action

        if previous_action is None:
            # Пропускаем и переходим к следующему Наблюдению
            continue

        # Если Намерение действие не содержит такой же Tool, то данное наблюдение не подходит
        if previous_action.tool != action.tool:
            # Пропускаем и переходим к следующему Наблюдению
            continue

        #  Валидируем обьект args_schema и сериализуем в JSON
        previous_arguments = args_schema.model_validate(previous_action.arguments).model_dump(mode="json")

        
        
        # Создаем Предыдущей Отпечаток попытки вызова инструмента
        previous_fingerprint = build_action_fingerprint(
            previous_action,
            previous_arguments,
        )

        # Сравниваем хеш отпечатков
        if previous_fingerprint != action_fingerprint:
            # Пропускаем и переходим к следующему наблюдению
            continue

        # Проверяем Наблюдение на успешность выполнения шага 
        if not previous_observation.success:
            # Пропускаем и переходим к следующему наблюдению
            continue



       # Получаем Функцию создания Представления состояния ресурса
        projection_fn = STATE_PROJECTIONS.get(action.tool)

        if projection_fn is None:
            # Для инструмента нет представления: состояние неизвестно
            # Немедленно выходит из цикла 
            break



        # Создаем представление состояния ресурса на основе предыдущего наблюдения
        projection = projection_fn(previous_observation.result or {})

        # Хеширование представления
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
# Функция создания Попытки вызова инструмента
############################################
def build_action_attempt(
    *,
    action: AgentAction,
    normalized_arguments: dict[str, Any],
    environment_fingerprint: str,
) -> ActionAttempt:
    """
    Функция создания Попытки вызова инструмента класса ActionAttempt, 
    используется в Executor и Replanner.
    """

    # Создание Отпечатка Попытки вызова инструмента
    action_fingerprint = build_action_fingerprint(
        action,
        normalized_arguments,
    )

    # Создание ключа дубликации
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
# Вспомогательная функция подсчёта попыток вызова инструмента
############################################
def count_duplicate_attempts(
    *,
    candidate: ActionAttempt,
    attempts: list[dict[str, Any]],
) -> int:
    """
    Вспомогательная функция подсчета попыток с тем же ключом дубликации.
    """
    return sum(
        1
        for attempt in attempts
        if ActionAttempt.model_validate(attempt).duplicate_key == candidate.duplicate_key
    )



############################################
# Функция проверки Количества попыток вызова инструмента
############################################
def is_duplicate_limit_reached(
    *,
    candidate: ActionAttempt,
    attempts: list[dict[str, Any]],
    max_attempts: int,
) -> bool:
    """
    Функция ограничения количества попыток вызова инструмента, используется в executor_node.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")

    return count_duplicate_attempts(candidate=candidate, attempts=attempts) >= max_attempts



