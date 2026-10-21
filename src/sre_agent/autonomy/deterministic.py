from dataclasses import dataclass

from datetime import datetime, timezone

from typing import Literal

from sre_agent.state import (
    ActionObservation,
    DeploymentReadyReplicasRule,
    PodReadyRule,
)


from sre_agent.state import DeterministicRule

# Новый строковой тип данных
CheckStatus = Literal[
    "passed",                   # Есть данные, и условие выполнено
    "failed",                   # Есть данные, и условие не выполнено
    "unknown"                   # Доказательств недостаточно
]

########################################################
# Класс хранения результата детерминированной проверки
########################################################
@dataclass(frozen=True)
class CheckResult:
    criterion: str
    status: CheckStatus
    evidence: str | None
    remaining_work: str| None


########################################################
# Специальная функция Python проверки детерминированного правила PodReadyRule
########################################################
def evaluate_pod_ready(
        rule: PodReadyRule,
        observations: list[ActionObservation],
        *,                                                          # разделитель параметров, который устанавливает правило: все аргументы после '*' передаются только по имени.
        now: datetime | None = None,
        max_age_seconds: int = 60, 
) -> CheckResult:

    """
    Специальная функция Python проверки состояния одной поды Ready="True".

    Функция связана с детерминированным правилом PodReadyRule (правило проверяет готовность одного Pod).
    
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

    # Внутренняя helper-функция
    def unknown(message: str) -> CheckResult:
        """Создание объекта класса CheckResult с статусом неизвестно"""
        return CheckResult(
            criterion = rule.criterion,
            status="unknown",
            evidence=None,
            remaining_work=message
        )

    """ Найти наблюдение observation для нужного ресурса Pod, который указан в rule детерминированном правиле. """

    # # 1. Найти наблюдения observations нужного Pod
    matching: list[ActionObservation] = []

    # итерируемся по фактическим результатам шагов
    for observation in observations:

        # Читаем из результата шага Python dict заполненный данными из Tool (см. _execute_kubernetes_api) 
        result = observation.result or {}

        if result.get("action") != "get_pod":
            # завершаем проверку объекта и переходим к следующему observation
            continue
        
        # Проверка совподения кластер алиас в фактическом результате шага 
        # и поле детерминированного правила  
        if result.get("cluster_alias", "").strip().lower() != rule.cluster_alias.strip().lower():
            # завершаем проверку объекта и переходим к следующему observation
            continue

        # Проверка совподения имени неймспейс в фактическом результате шага 
        # и поле детерминированного правила  
        if result.get("namespace").strip().lower() != rule.namespace.strip().lower():
            # завершаем проверку объекта и переходим к следующему observation
            continue

        
        # Читаем имя пода из фактического результата шага
        pod = result.get("pod")

        if not isinstance(pod, dict):
            # завершаем проверку объекта и переходим к следующему observation
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
              for observation in matching
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



########################################################
# Специальная функция Python проверки детерминированного правила DeploymentReadyReplicasRule
########################################################
def evaluate_deployment_ready_replicas(
    rule: DeploymentReadyReplicasRule,
    observations: list[ActionObservation],
    *,
    now: datetime | None = None,
    max_age_seconds: int = 60,
) -> CheckResult:
    """
    Специальная функция Python проверки состояния ready_replicas >= spec.replicas в одном Deployment.

    Функция жестко связана с детерминированным правилом DeploymentReadyReplicasRule.
    
    Ответственность:
    1) Найти наблюдение observation для нужного ресурса Deployment, который указан в rule детерминированном правиле;
    2) Проверить актуальность и пригодность данных в наблюдении observation шага по нужному ресурсу;
    3) Найти в найденном наблюдении observation данные по Deployment;
    4) Проверить фиксированное условие ready_replicas >= spec.replicas.
    """

    # Создаем переменную для определения актуальности наблюдения
    if now is None:
        now = datetime.now(timezone.utc)

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must contain a timezone")

    # Проверка входного параметра 
    if (type(max_age_seconds) is not int or max_age_seconds < 0):
        raise ValueError(
            "max_age_seconds must be a non-negative integer"
        )

    # Создание переменой ресурс
    resource = f"{rule.cluster_alias}/{rule.namespace}/{rule.deployment_name}"

    # Создание helper-функция 
    def unknown(message: str) -> CheckResult:
        return CheckResult(
            criterion=rule.criterion,
            status="unknown",
            evidence=None,
            remaining_work=message,
        )


    """ Найти наблюдение observation для нужного ресурса Deployment, который указан в rule детерминированном правиле. """

    # Создаем контейнер для хранения наблюдений observation с нужным ресурсом Deployment 
    matching: list[ActionObservation] = []


    for observation in observations:
        result = observation.result

        if not isinstance(result, dict):
           # завершаем проверку объекта и переходим к следующему observation
            continue


        if result.get("action") != "get_deployment":
             # завершаем проверку объекта и переходим к следующему observation
            continue

        # Читаем из observation.result.result_metadataкоторый содержит
        # значения cluster_alias и cluster_context
        cluster_alias = result.get("cluster_alias")

        if not isinstance(cluster_alias, str):
            # переходим к следующему наблюдению observation 
            continue

        if cluster_alias.strip().lower() != rule.cluster_alias.strip().lower():
            # переходим к следующему наблюдению observation 
            continue

        if result.get("namespace") != rule.namespace:
            # переходим к следующему наблюдению observation 
            continue        

        if result.get("deployment_name") != rule.deployment_name:
            # переходим к следующему наблюдению observation 
            continue

        # Добавляем наблюдения observation нужного Deployment
        matching.append(observation)

    # Проверка на отсутствие нужных наблюдений в контейнере 
    if not matching:
        # возращаем объект CheckResult с атрибутом remaining_work включающим текст
        # с целью создания нового execution_plan в рамках новой итерации lifecycle
        return unknown(
            f"Прочитать Deployment {resource}"
        )


    """ 2. Без времени нельзя надёжно выбрать последнее чтение. """

    for observation in matching:
        # Читаем время созднания наблюдения observation
        timestamp = observation.observed_at

        if (
            timestamp is None
            or timestamp.tzinfo is None
            or timestamp.utcoffset() is None
        ):
            # возращаем объект CheckResult с атрибутом remaining_work включающим текст
            # с целью создания нового execution_plan в рамках новой итерации lifecycle
            return unknown(
                f"Повторно прочитать Deployment {resource}: нет времени наблюдения с часовым поясом"
                )

        # Находим самое свежую дату создания observation в контейнере сохраненных наблюдений с нужным ресурсом Deployment
        latest_time = max(observation.observed_at for observation in matching)

        # Находим самое свежее observation в контейнере сохраненных наблюдений 
        # с нужным ресурсом Deployment по найденной дате
        latest = [ 
            observation 
            for observation in matching
            if observation.observed_at == latest_time
            ]


        if len(latest) != 1:
            # возращаем объект CheckResult с атрибутом remaining_work включающим текст
            # с целью создания нового execution_plan в рамках новой итерации lifecycle
            return unknown(
                f"Повторно прочитать Deployment {resource}: последнее наблюдение неоднозначно"
            ) 

        # Находим самое свежее наблюдение связанное с нужным ресурсом Deployment
        observation = latest[0]
        # Читаем снова дату из самого свежего наблюдения
        timestamp = observation.observed_at
        assert timestamp is not None

        # Проверяем актуальность найденного наблюдения
        age = (now - timestamp).total_seconds()
    
        
        if age < 0 or age > max_age_seconds:
            # возращаем объект CheckResult с атрибутом remaining_work включающим текст
            # с целью создания нового execution_plan в рамках новой итерации lifecycle
            return unknown(
                f"Повторно прочитать Deployment {resource}: наблюдение устарело или имеет время из будущего"            
            )

        if not observation.success:
            return unknown(
                f"Повторно прочитать Deployment {resource}: последнее наблюдение завершилось ошибкой"
        )

    
    """  3. Сохраняем консервативную политику твоей Pod-проверки: ошибка после подтверждения требует нового чтения. Важно для ошибок с result=None. """
    
    # Поиск наблюдений с НЕ УСПЕШНЫМ выполнением STEP в execution_plan
    for item in observations:
        if item.success:
            continue

        # Определение даты создания наблюдения на не успешно выполненом STEP
        failure_time = item.observed_at

        if (
            failure_time is None
            or failure_time.tzinfo is None
            or failure_time.utcoffset() is None
            # сравнение даты создания наблюдения на не успешно выполненом шаге
            # и найденное ранее свежее наблюдение связанное с нужным ресурсом Deployment
            or failure_time >= timestamp
        ):
            # возращаем объект CheckResult с атрибутом remaining_work включающим текст
            # с целью создания нового execution_plan в рамках новой итерации lifecycle            
            return unknown(
                f"Повторно прочитать Deployment {resource} после неуспешного действия" 
            )


    """ 4. Проверить структуру и идентичность самого объекта. """
    # Читаем результат dict из наблюдения, 
    result = observation.result

    assert isinstance(result, dict)

    # читаем бизнес данные по ресурсу deployment.to_dict()
    deployment = result.get("deployment")

    if not isinstance(deployment, dict):
        # возращаем объект CheckResult с атрибутом remaining_work включающим текст
        # с целью создания нового execution_plan в рамках новой итерации lifecycle
        return unknown(
            "В результате отсутствует объект Deployment"
        )

    # Читаем metadata из обьекта deployment сериализованного в dict
    metadata = deployment.get("metadata")

    # Читаем spec из обьекта deployment сериализованного в dict
    spec = deployment.get("spec")

    # Читаем status из обьекта deployment сериализованного в dict
    status = deployment.get("status")

    # Проверка типов бизнес данных metadata, spec или status
    if not all( isinstance(value, dict) for value in (metadata, spec, status)):
        return unknown(
            "В Deployment отсутствуют metadata, spec или status"
        )

    # Проверка идентичности ресурса на соотвествие в детермированном правиле
    if (
        metadata.get("name") != rule.deployment_name 
        or 
        metadata.get("namespace") != rule.namespace
    ):
        return unknown(
            "Метаданные Deployment не соответствуют правилу"
        )

    # Проверка состояния Deployment что он не удаляется 
    if metadata.get("deletion_timestamp") is not None:
        return unknown(
            "Deployment удаляется: готовность не подтверждена"
        )
    
    """ 5. Проверить, что контроллер обработал текущее поколенее конфигурации spec Deployment. """

    # Текущее поколение желаемой конфигурации .metadata.generation в Deployment
    # При изменении spec, например образа или количества реплик, Kubernetes увеличивает этот номер.
    generation = metadata.get("generation")

    # Контроллер Deployment уже увидел поколение и отразил его обработку в статусе .status.observedGeneration
    observed_generation = status.get("observed_generation")


    # Проверка корректности значений .metadata.generation и .status.observerdGeneration
    if type(generation) is not int or generation < 1:
        return unknown(
            "Отсутствует корректное значение generation поколение конфигурации Deployment"
        )

    if type(observed_generation) is not int or observed_generation < 1:
        return unknown(
            "Отсутствует корректное значение observed_generation поколение конфигурации Deployment"
        )

    # Проверка обработки Deployment контроллером последней желаемой конфигурации spec
    if observed_generation < generation:
        return unknown(
            "Дождаться обработки текущего желаемого поколения Deployment и повторить чтение"
        )

    
    """ 6. Получить и проверить сравниваемые значения. """

    # Читаем значение .spec.replicas из спецификации Deployment, полученную из найденного наблюдения observation
    desired_replicas = spec.get("replicas")

    # Читаем значение .status.readyReplicas из состояния Deployment, 
    # полученную из найденного наблюдения observation
    ready_replicas = status.get("ready_replicas")

    # Проверка корректности типа данных и значений 
    if (type(desired_replicas) is not int or desired_replicas < 0):
        return unknown(
            "Нет корректных целочисленных значений "
            "spec.replicas"
        )

    if (type(ready_replicas) is not int or ready_replicas < 0):
        return unknown(
            "Нет корректных целочисленных значений "
            "status.ready_replicas"
        )

    # Формируем доказательство
    evidence = (
        f"action_id={observation.action_id}; "
        f"resource={resource}; "
        f"observed_at={timestamp.isoformat()}; "
        f"generation={generation}; "
        f"observed_generation={observed_generation}; "
        f"ready_replicas={ready_replicas}; "
        f"desired_replicas={desired_replicas}"
    )


    """ 7. Здесь выполняется проверка самого условия критерия. """
    # Пригодные данные подтверждают выпонение условия
    if ready_replicas >= desired_replicas:
        return CheckResult(
            criterion=rule.criterion,
            status = "passed",
            evidence=evidence,
            remaining_work=None,
        )

    # Пригодные данные опровергают выпонение условия
    return CheckResult(
        criterion=rule.criterion,
        status="failed",
        evidence=evidence,
        remaining_work=(
            f"У Deployment {resource} готовы {ready_replicas} из {desired_replicas} реплик. "
            "Выяснить причину неготовности и повторить проверку."
        ),
    )


###################################
# Диспетчер детерминированных правил
###################################
def evaluate_deterministic_rule(
 rule: DeterministicRule,
    observations: list[ActionObservation],
    *,
    now: datetime | None = None,
    max_age_seconds: int = 60,
) ->  CheckResult:
    # диспетчер выбирает функцию по классу PodReadyRule
    if isinstance(rule, PodReadyRule):
        return evaluate_pod_ready(
            rule,
            observations,
            now=now,
            max_age_seconds=max_age_seconds,
        )
    # диспетчер выбирает функцию по классу DeploymentReadyReplicasRule
    if isinstance(rule, DeploymentReadyReplicasRule):
        return evaluate_deployment_ready_replicas(
            rule,
            observations,
            now=now,
            max_age_seconds=max_age_seconds,
        )

    raise TypeError(
        f"Unsupported deterministic rule: {type(rule).__name__}"
    )