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

############################################
# Вспомогательная функция подсчёта попыток с тем же ключом дубликации
############################################
def count_duplicate_attempts(
    *,
    candidate: ActionAttempt,
    attempts: list[dict[str, Any]],
) -> int:
    return sum(
        1
        for raw in attempts
        if ActionAttempt.model_validate(raw).duplicate_key == candidate.duplicate_key
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

    return count_duplicate_attempts(candidate=candidate, attempts=attempts) >= max_attempts


###########################################
# Вспомогательная функция представления состояния контейнера
###########################################
def _container_state_projection(container_status: dict[str, Any]) -> dict[str, Any]:
    """
    Сжимает state/last_state контейнера до вида состояния и причины без timestamps.
    """

    def _state_kind(state: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(state, dict):
            return None

        # В to_dict() заполнен ровно один из ключей running/waiting/terminated
        for kind in ("running", "waiting", "terminated"):
            details = state.get(kind)
            if isinstance(details, dict):
                return {
                    "kind": kind,
                    "reason": details.get("reason"),
                    "exit_code": details.get("exit_code"),
                }
        return None

    return {
        "name": container_status.get("name"),
        "ready": container_status.get("ready"),
        "started": container_status.get("started"),
        "restart_count": container_status.get("restart_count") or 0,
        "state": _state_kind(container_status.get("state")),
        "last_state": _state_kind(container_status.get("last_state")),
    }


###########################################
# Вспомогательная функция создания Pod представления (get_pod_tool)
###########################################
def pod_state_projection(result: dict[str, Any]) -> dict[str, Any] | None:

    pod = result.get("pod")

    if not isinstance(pod, dict):
        return None

    metadata = pod.get("metadata") or {}
    status = pod.get("status") or {}

    uid = metadata.get("uid")

    if not isinstance(uid, str) or not uid:
        return None

    return {
        "kind": "pod",
        "uid": uid,
        "phase": status.get("phase"),
        # Только type/status: last_probe_time меняется при каждой пробе
        "conditions": sorted(
            (c.get("type"), c.get("status"))
            for c in (status.get("conditions") or [])
        ),
        "containers": sorted(
            (
                _container_state_projection(cs)
                for cs in (status.get("container_statuses") or [])
            ),
            key=lambda item: item["name"] or "",
        ),
    }


###########################################
# Вспомогательная функция создания представления списка Pod (list_pods_tool)
###########################################
def pod_list_state_projection(result: dict[str, Any]) -> dict[str, Any] | None:

    pods = result.get("pods")

    if not isinstance(pods, list):
        return None

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
# Вспомогательная функция создания представления событий (get_pod_events_tool, get_node_events_tool)
###########################################
def events_state_projection(result: dict[str, Any]) -> dict[str, Any] | None:

    events = result.get("events")

    if not isinstance(events, list):
        return None

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
            for event in events
            if isinstance(event, dict)
        ),
    }


###########################################
# Вспомогательная функция создания представления логов (get_pod_logs_tool)
###########################################
def logs_state_projection(result: dict[str, Any]) -> dict[str, Any] | None:

    logs = result.get("logs")

    if not isinstance(logs, str):
        return None

    # Логи читаются с timestamps=True: любая новая строка меняет хеш
    return {
        "kind": "logs",
        "logs_hash": stable_hash(logs),
    }


###########################################
# Вспомогательная функция создания представления Node (get_node_tool, list_nodes_tool)
###########################################
def _node_conditions(conditions: list[Any] | None) -> list[tuple]:
    return sorted(
        (c.get("type"), c.get("status"), c.get("reason"))
        for c in (conditions or [])
        if isinstance(c, dict)
    )


def node_state_projection(result: dict[str, Any]) -> dict[str, Any] | None:

    node = result.get("node")

    if not isinstance(node, dict):
        return None

    metadata = node.get("metadata") or {}
    spec = node.get("spec") or {}
    status = node.get("status") or {}

    uid = metadata.get("uid")

    if not isinstance(uid, str) or not uid:
        return None

    return {
        "kind": "node",
        "uid": uid,
        "unschedulable": bool(spec.get("unschedulable")),
        "conditions": _node_conditions(status.get("conditions")),
    }


def node_list_state_projection(result: dict[str, Any]) -> dict[str, Any] | None:

    nodes = result.get("nodes")

    if not isinstance(nodes, list):
        return None

    return {
        "kind": "node_list",
        "nodes": sorted(
            (node.get("name"), _node_conditions(node.get("conditions")))
            for node in nodes
            if isinstance(node, dict)
        ),
    }


###########################################
# Реестр функций представления состояния по инструменту
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
    Cоздания отпечатка состояния ресурса по последнему успешному идентичному вызову.
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


       # Получаем функцию представления состояния для инструмента
        projection_fn = STATE_PROJECTIONS.get(action.tool)

        if projection_fn is None:
            # Для инструмента нет представления: состояние неизвестно
            break

        # Создаем представление состояния ресурса
        projection = projection_fn(observation.result or {})

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