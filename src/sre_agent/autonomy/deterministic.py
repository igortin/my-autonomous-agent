from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sre_agent.state import (
    ActionObservation,
    PodReadyRule,
)

# Новый строковой тип данных
CheckStatus = Literal[
    "passed",                   # Есть данные, и условие выполнено
    "failed",                   # Есть данные, и условие не выполнено
    "unknown"                   # Доказательств недостаточно
]

# Класс хранения результата детерминированной проверки
@dataclass(frozen=True)
class CheckResult:
    criterion: str
    status: CheckStatus
    evidence: str | None
    remaining_work: str| None





def evaluate_pod_ready(
        rule: PodReadyRule,
        observations: list[ActionObservation],
        *,                                                          # разделитель параметров, который устанавливает правило: все аргументы после '*' передаются только по имени.
        now: datetime | None = None,
        max_age_seconds: int = 60, 
) -> CheckResult:

    """
    Специальная функция проверки состояния одной поды Ready="True".

    Функция жестко должна быть связана с детерминированным правилом PodReadyRule (правило проверяет готовность одного Pod).
    
    Для других правил нужны отдельные аналогичные функции. 

    Ответственность:
    1) Найти наблюдение observation для нужного ресурса Pod, который указан в rule детерминированном правиле;
    2) Проверить актуальность и пригодность данных в наблюдении observation шага по нужному ресурсу Pod;
    3) Найти Сondition с type == Ready в найденном наблюдении observation;
    4) Проверить фиксированное условие готовности поды Сonditions.status == "True".
    """

    # Если время проверки не передано, берём текущее время в UTC
    if now is None:
        now = datetime.now(timezone.utc)

    # Создадим строго типизироанный список
    matching: list[ActionObservation] = []

    # Внутренняя Helper функция
    def unknown(message: str) -> CheckResult:
        """Создание объекта класса CheckResult с статусом неизвестно"""
        return CheckResult(
            criterion = rule.criterion,
            status="unknown",
            evidence=None,
            remaining_work=message
        )

    """ Найти наблюдение observation для нужного ресурса Pod, который указан в rule детерминированном правиле. """

    # Определение нового списка шагов подходящих для проверки детерминированным правилом
    matching: list[ActionObservation] = []

    # итерируемся по фактическим результатам шагов
    for observation in observations:

        # Читаем из результата шага Python dict заполненный данными из Tool (см. _execute_kubernetes_api) 
        result = observation.result or {}

        if result.get("action") != "get_pod":
            # завершаем проверку объекта observation и переходим к следующей итерации 
            continue
        
        # Проверка совподения кластер алиас в фактическом результате шага 
        # и поле детерминированного правила  
        if result.get("cluster_alias", "").strip().lower() != rule.cluster_alias.strip().lower():
            # завершаем проверку объекта observation и переходим к следующей итерации 
            continue

        # Проверка совподения имени неймспейс в фактическом результате шага 
        # и поле детерминированного правила  
        if result.get("namespace").strip().lower() != rule.namespace.strip().lower():
            # завершаем проверку объекта observation и переходим к следующей итерации 
            continue

        
        # Читаем имя пода из фактического результата шага
        pod = result.get("pod")

        if not isinstance(pod, dict):
            # завершаем проверку объекта observation и переходим к следующей итерации 
            continue

        # Читаем метаданные из фактического результата шага
        metadata = pod.get("metadata")

        if not isinstance(metadata, dict):
            # завершаем проверку объекта observation и переходим к следующей итерации 
            continue

        # Проверка метадата относиться к проверяемому под
        if metadata.get("name") != rule.pod_name:
            # завершаем проверку объекта observation и переходим к следующей итерации 
            continue

        # добавление фактического результата шага
        matching.append(observation)



    # Ошибка чтения другого ресурса поды тоже может потребовать повторной проверки
    if not matching:
        # возращаем объект с атрибутом remaining_work включающим ниже текст 
        return unknown(
            "Прочитать под "
            f"{rule.cluster_alias}/{rule.namespace}/{rule.pod_name}"
            )



    """ Проверить актуальность и пригодность данных в наблюдении observation шага по нужному ресурсу Pod. """

    # Без времени нельзя надёжно выбрать актуальное наблюдение.
    for observation in matching:
        # Получаем время создания наблюдения 
        timestamp = observation.observed_at

        if  (timestamp is None or timestamp.tzinfo is None or  timestamp.utcoffset() is None):
            # возращаем объект CheckResult с атрибутом remaining_work включающим ниже текст 
            return unknown(
                "Повторно прочитать Pod: у наблюдения нет времени получения с часовым поясом"
            )

    # Находим самое свежее время наблюдения среди объектов в matching
    latest_time = max(observation.observed_at for observation in matching) 

    # Создаем список с одним саммым свежим наблюдением
    latest = [ observation 
              for observation in observations
              if observation.observed_at == latest_time
    ]

    if len(latest) != 1:
        # возращаем объект CheckResult с атрибутом remaining_work включающим ниже текст 
        return unknown(
            "Повторно прочитать Pod: несколько наблюдений имеют одинаковое время получения"
        )

    # Получаем самое свежее время наблюдения
    observation = latest[0]

    # Считаем сколько времени прошло с момента создания наблюдения
    age = (now - observation.observed_at).total_seconds()

    # Проверка на устарение наблюдения 
    if age < 0 or age > max_age_seconds:
        return unknown(
            "Повторно прочитать Pod: наблюдение устарело или имеет некорректное время"
        )


    """ Проверка успешности выполнения шага создавшее найденное наблюдение (ActionObservation). """

    # Проверка успешности выполнения шага создавшее найденное наблюдение
    if not observation.success:
        # возращаем объект CheckResult с атрибутом remaining_work включающим ниже текст 
        return unknown(
            "Повторно прочитать Pod: последнее чтение завершилось ошибкой"
        )

    """ Проверка, что следующие шаги были также успешны, после шага с найденным наблюдением (ActionObservation). """

    # Консервативно не используем найденое подтверждение,
    # если после него было неуспешное вполнение шагов.
    for item in observations:

        # Проверка на успшность выполения шага
        if item.success:
            # переходим к следующей итерации проверки объекта 
            # в случаем шаг был успшеным
            continue

        # Читаем время создания наблюдения неуспешного шага
        timestamp = item.observed_at

        if (
            timestamp is None
            or timestamp.tzinfo is None
            or timestamp.utcoffset() is None
            # Проверяем поледующий неуспешный шаг был создан после ранее НАЙДЕННОГО наблюдения  
            or timestamp >= observation.observed_at
        ):
            return unknown(
                "Повторно прочитать Pod после неуспешного действия: актуальность подтверждения не установлена"
            )


    """ Найти Сondition с type == Ready в найденном наблюдении observation. """

    # Читаем данные по POD-у из найденного наблюдения observation
    # полученные из Tool на action=get_pod
    # (см. _execute_kubernetes_api)
    
    """
        Данные содержат output: kubectl get pod colvir-front-test -n colvir-test -o json  | jq .status.conditions

        {
            "lastProbeTime": null,
            "lastTransitionTime": "2026-09-28T14:45:47Z",
            "observedGeneration": 1,
            "status": "True",
            "type": "ContainersReady"
        },
        {
            "lastProbeTime": null,
            "lastTransitionTime": "2026-09-28T14:45:48Z",
            "observedGeneration": 1,
            "status": "True",
            "type": "Ready"
        },
    """
    
    pod = observation.result["pod"]

    # Получение status пода из найденного наблюдения 
    # (kubectl get pod colvir-front-test -n colvir-test -o json  | jq .status)
    status = pod.get("status")

    if not isinstance(status, dict):
        # возращаем объект CheckResult с атрибутом remaining_work включающим ниже текст 
        return unknown(
            "Повторно прочитать Pod: отсутствует status"
        )

    # Получение данных Conditions пода из найденного наблюдения
    # (kubectl get pod colvir-front-test -n colvir-test -o json  | jq .status.conditions)
    conditions = status.get("conditions")

    if not isinstance(conditions, list):
        # возращаем объект CheckResult с атрибутом remaining_work включающим ниже текст 
        return unknown(
            "Повторно прочитать Pod: отсутствует список conditions"
        )

    # Создаем список по Conditions c kubernetes built-in типом "type": "Ready"
    ready_conditions = [
        condition
        for condition in conditions
        if isinstance(condition, dict) and condition.get("type") == "Ready"
    ]

    if len(ready_conditions) != 1:
        # возращаем объект CheckResult с атрибутом remaining_work включающим ниже текст 
        return unknown(
            "Повторно прочитать Pod: condition Ready отсутствует или неоднозначна"
        )


   
    """ Проверить фиксированное условие готовности поды Сonditions.status == "True". """

    # Читаем поле status тип данных str 
    # из pod Сonditions
    # с типом "type": "Ready"
    value = ready_conditions[0].get("status")

    # Формируем evidence и записываем полученное занчение status
    source = (
        f"action_id={observation.action_id}; "
        f"resource={rule.cluster_alias}/{rule.namespace}/{rule.pod_name}; "
        f"observed_at={observation.observed_at.isoformat()}; "
        f"pod.status.conditions[type=Ready].status={value!r}"
    )


    # Возращаем объект при успешной проверке детерминированного правила  
    if value == "True":
        return CheckResult(
            criterion=rule.criterion,
            status="passed",
            evidence=source,
            remaining_work=None,
        )

    # Возращаем объект при неуспешной проверке детерминированного правила  
    if value == "False":
        return CheckResult(
            criterion=rule.criterion,
            status="failed",
            evidence=source,
            remaining_work=(
                "Pod не готов. Получить события и сведения "
                "о контейнерах, затем повторно проверить Ready"
            ),
        )

    
    # Обработчик в value некорректного значения 
    return unknown(
        "Повторно проверить Pod: Ready имеет значение "
        f"{value!r}, которое не подтверждает готовность"
    )



