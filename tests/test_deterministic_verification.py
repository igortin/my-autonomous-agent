
import pytest
from datetime import datetime, timezone, timedelta
from sre_agent.autonomy.deterministic import (
    evaluate_pod_ready,
)
from sre_agent.state import (
    ActionObservation,
    PodReadyRule,
)

""" Тесты функции детерминированной проверки """

# Определение текущей даты и времени
NOW = datetime(2026, 10, 11, 10, 0, 0, tzinfo=timezone.utc)

# Создание тестового ДЕТЕРМИНИРОВАННОГО правила
@pytest.fixture
def rule():
    return PodReadyRule(
        kind="pod_ready",
        criterion="Pod payment-api-1 имеет Ready=True",
        cluster_alias="docker-desktop",
        namespace="payments",
        pod_name="payment-api-1",
    )


# Тестовое наблюдение observation
def make_observation(
    ready: str,
    *,
    observed_at: datetime = NOW,
    namespace: str = "payments",
) -> ActionObservation:
    return ActionObservation(
        action_id="inspect-pod",
        success=True,
        result={
            "action": "get_pod",
            "cluster_alias": "docker-desktop",
            "namespace": namespace,
            "pod": {
                "metadata": {
                    "name": "payment-api-1",
                    "namespace": namespace,
                },
                "status": {
                    "conditions": [
                        {
                            "type": "Ready",
                            "status": ready,
                        },
                    ],
                },
            },
        },
        error=None,
        observed_at=observed_at,
    )



# Параметры тестов
@pytest.mark.parametrize(
    ("ready", "expected"),
    [
        ("True", "passed"),
        ("False", "failed"),
        ("Unknown", "unknown"),
    ],
)

############################################
# Тестирование спецальной функции готовности одной поды с разными статусами
############################################
def test_ready_condition(rule, ready, expected):
    # Проверка состояния одно поды Ready="True" и возращет инстанс класса CheckResult
    result = evaluate_pod_ready(
        rule,
        [make_observation(ready)],                  # <- массив из одного тестового observation
        now=NOW,
        )

    assert result.status == expected


############################################
# Тестирование спецальной функции готовности одной поды с некорректным namespace
############################################
def test_other_namespace_is_not_evidence(rule):
    """
    В функции evaluate_pod_ready() сравнивается rule.namespace и observation.result.namespace
    При не совпадаении значений, создается решение CheckResult.status = unknown 
    и требуется повторная итерация lifecycle с новым execution_plan

    Проверяется:
    - правильный ресурс;
    """
    # Проверка состояния одно поды Ready="True" и возращет инстанс класса CheckResult
    result = evaluate_pod_ready(
        rule,
        [make_observation("True", namespace="namespace_name_not_same_as_in_rule")],
        now=NOW,
        )

    assert result.status == "unknown"


############################################
# Тестирование спецальной функции готовности одной поды с устравшим наблюдением (observation)
############################################
def test_stale_observation_is_not_evidence(rule):
    """ 
    В функции evaluate_pod_ready() установлено max_age_seconds по умолчанию 60 сек
    все наблюдения observation более старее не рассматриваются 
    и требуется повторная итерация lifecycle с новым execution_plan

    Проверяется:
    - актуальность данных;
    """


    # Проверка состояния одно поды Ready="True" и возращет инстанс класса CheckResult
    result = evaluate_pod_ready(
        rule,
        [
            make_observation(
            "True",
            observed_at=NOW-timedelta(minutes=5),
            )
        ],
        now=NOW,
    )

    assert result.status ==  "unknown"


############################################
# Тестирование спецальной функции готовности одной поды с заменой старого новым наблюдением (observation)
############################################
def test_newer_false_replaces_older_true(rule):
    """
    В функции evaluate_pod_ready() обрабатывается самое свежее время наблюдение

     Проверяется:
        - замена старого результата новым наблюдением obsevation;
    """
    # Создаем наблюдение с pod.conditions.status=True
    older = make_observation(
        "True",
        observed_at=NOW - timedelta(seconds=10),
    )

    # Создаем новое наблюдение наблюдение с pod.conditions.status=False
    newer = make_observation(
        "False",
        observed_at=NOW,
    )

    # Проверка состояния одно поды Ready="True" и возращет инстанс класса CheckResult
    result = evaluate_pod_ready(
        rule,
        [older, newer],                     # <- в списке фактические резултаты 2 шагов (наблюдения/observations)
        now=NOW,
    )

    assert result.status == "failed"

############################################
# Тестирование спецальной функции готовности одной поды c наблюдением observation без даты создания
############################################
def test_missing_timestamp_is_unknown(rule):
    """
    В функции evaluate_pod_ready() проверяется наличие в наблюдении observation устновленного времени его создания
    иначе требуется повторная итерация lifecycle с новым execution_plan

    Проверяется:
    - отсутствие времени;
    """
    obsevation = make_observation("True")
    
    obsevation.observed_at = None

    result = evaluate_pod_ready(
            rule,
            [obsevation],                    
            now=NOW,
        )

    assert result.status == "unknown"


def test_failure_after_success_requires_new_read(rule):
    """
    Тестирование что следующие шаги были также успешны, после шага с успешным наблюдением observation
    иначе требуется повторная итерация lifecycle с новым execution_plan

    Проверяется:
    - ошибка после старого подтверждения.
    """
    
    # Создание успешного наблюдения  
    success = make_observation(
        "True",
        observed_at=NOW - timedelta(seconds=10),
    )

    # Создание неуспешного наблюдения  
    failure = ActionObservation(
        action_id="failed-read",
        success=False,
        result=None,
        error="Kubernetes API timeout",
        observed_at=NOW,
    )

    result = evaluate_pod_ready(
        rule,
        [success, failure],                    
        now=NOW,
    )

    
    assert result.status == "unknown"
