from datetime import datetime, timedelta, timezone
from sre_agent.autonomy.deterministic import (
    evaluate_deployment_ready_replicas,
    evaluate_deterministic_rule,
)

import pytest

from sre_agent.state import (
    ActionObservation,
    AgentGoal,
    DeploymentReadyReplicasRule,
)



NOW = datetime(
    2026, 10, 18, 7, 0, 0,
    tzinfo=timezone.utc,
)

CRITERION = "У Deployment colvir-front-test все желаемые реплики готовы."

###############################################
# Тестовое детерминированное правило для проверки готовности Deployment replicas
###############################################
@pytest.fixture
def rule():
    return DeploymentReadyReplicasRule(
        kind="deployment_ready_replicas",
        criterion=CRITERION,
        cluster_alias="docker-desktop",
        namespace="payments",
        deployment_name="payment-api",
    )




###############################################
# Тестовое наблюдение observation по Deployment
###############################################
def make_observation(
    *,
    ready=3,
    desired=3,
    generation=5,
    observed_generation=5,
    observed_at=NOW,
    namespace="payments",
):
    return ActionObservation(
        action_id="inspect-deployment",
        success=True,                                               # Шаг выполнился успешно
        error=None,
        observed_at=observed_at,
        result={
            "action": "get_deployment",
            "cluster_alias": "docker-desktop",
            "namespace": namespace,
            "deployment_name": "payment-api",
            "deployment": {
                "metadata": {
                    "name": "payment-api",
                    "namespace": namespace,
                    "generation": generation,
                },
                "spec": {
                    "replicas": desired,
                },
                "status": {
                    "ready_replicas": ready,
                    "observed_generation": observed_generation,
                },
            },
        },
    )


###############################################
# Входные тестовые параметры 
###############################################
@pytest.mark.parametrize(
    ("ready", "desired", "expected"),
    [
        (3, 3, "passed"),
        (4, 3, "passed"),
        (2, 3, "failed"),
        (0, 3, "failed"),
        (0, 0, "passed"), 
    ],
)
###############################################
# Тестирование функции проверки детерминированного правила DeploymentReadyReplicasRule
###############################################
def test_replica_comparison(
    rule,                                               # <-- Тестовое детерминированное правило для проверки готовности Deployment replicas
    ready,
    desired,
    expected,
):
    """
    Тестрование функции evaluate_deployment_ready_replicas() на сравнение значений ready и desired
    """

    # Оценка наблюдений согласно детерминированному правилу DeploymentReadyReplicasRule
    result = evaluate_deployment_ready_replicas(
        rule,
        [ 
            make_observation(
                ready=ready, 
                desired=desired, 
            ) 
        ],
        now=NOW,
    )

    # Тесты
    assert result.status == expected
    assert result.criterion == CRITERION
    assert result.evidence is not None


###############################################
# Входные тестовые параметры (не корректные)
###############################################
@pytest.mark.parametrize(
    ("ready", "desired"),
    [
        (None, 3),
        ("3", 3),
        (True, 3),
        (-1, 3),
        (3, None),
        (3, "3"),
        (3, True),
        (3, -1),
    ],
)

###############################################
# Тестирование функции проверки детерминированного правила с некорректынми входными параметрами
###############################################
def test_invalid_replica_counts_are_unknown(
    rule,
    ready,
    desired,
):
    """
    Тестрование функции evaluate_deployment_ready_replicas() на получение 
    и проверку типов данных сравнимых значений ready и desired
    """
    # Оценка наблюдений согласно детерминированному правилу DeploymentReadyReplicasRule
    result = evaluate_deployment_ready_replicas(
        rule,
        [
            make_observation(
                ready=ready,
                desired=desired,
            )
        ],
        now=NOW,
    )

    assert result.status == "unknown"

    # Нет корректных целочисленных значений spec.replicas"
    assert result.remaining_work is not None



###############################################
# Входные тестовые параметры
###############################################
@pytest.mark.parametrize(
    "timestamp",
    [
        None,
        NOW - timedelta(seconds=61),
        NOW + timedelta(seconds=1),
    ],
)
###############################################
# Тестирование функции проверки детерминированного правила с мекой даты
###############################################
def test_invalid_or_stale_time_is_unknown(
    rule, timestamp
):    
    """
    Тестрование функции evaluate_deployment_ready_replicas() 
    сравнения значений ready и desired по наблюдениям с некорректными метками даты
    тоесть наблюдение либо устравшее или из будущего
    """
    result = evaluate_deployment_ready_replicas(
        rule,
        [
            make_observation(observed_at=timestamp)
        ],
        now=NOW
    )

    assert result.status == "unknown"

    # Повторно прочитать Deployment {resource}: наблюдение устарело или имеет время из будущего"
    assert result.remaining_work is not None 


###############################################
# Тестирование функции проверки детерминированного правила с мекой даты
###############################################
def test_unprocessed_generation_is_unknown(rule):
    """
    Тестрование функции evaluate_deployment_ready_replicas() 
    сравнения значений ready и desired при еще необработанной конфигурации
    Deployment, тоесть .status.observedGeneration < .metadata.generation
    """
    result = evaluate_deployment_ready_replicas(
        rule,
        [
            make_observation(
                generation=6,
                observed_generation=5,
            )
        ],
        now=NOW,
    )

    assert result.status == "unknown"

    # Дождаться обработки текущего желаемого поколения Deployment и повторить чтение
    assert result.remaining_work is not None

###############################################
# Тестирование функции проверки детерминированного правила с мекой даты
###############################################
def test_newer_failure_replaces_older_success(rule):
    """
    Тестрование функции evaluate_deployment_ready_replicas() 
    сравнения значений ready и desired когда 
    предыдущее наблюдение содержит бизнес данные для успешного результата проверки, 
    а новое наблюдение содержит бизнес данные для не успешного результата проверки. 
    """

    # Наблюдение содержащее бизнес данные для passed результата проверки 
    older = make_observation(
        ready=3,
        desired=3,
        observed_at=NOW - timedelta(seconds=10),
    )
    # Наблюдение содержащее бизнес данные для failed результата проверки 
    newer = make_observation(
        ready=1,
        desired=3,
        observed_at=NOW,
    )

    result = evaluate_deployment_ready_replicas(
        rule,
        [
            older,
            newer,
        ],
        now=NOW
    )

    assert result.status == "failed"

    # У Deployment {resource} готовы {ready_replicas} из {desired_replicas} реплик. Выяснить причину неготовности и повторить проверку.
    assert result.remaining_work is not None

###############################################
# Тестирование функции проверки детерминированного правила с мекой даты
###############################################
def test_error_after_read_requires_new_read(rule):
    """
    Тестрование функции evaluate_deployment_ready_replicas() 
    сравнения значений ready и desired когда 
    предыдущее наблюдение содержит бизнес данные для успешного результата проверки, 
    а новое наблюдение содержит ошибку чтения Kuberneets API тоесть шаг выполнился не успешно по сбору бизнес данных. 
    """

    # Наблюдение ActionObservation содержащее бизнес данные для passed результата проверки
    success = make_observation(
        observed_at=NOW - timedelta(seconds=10),
    )

    # Наблюдение ActionObservation не содержащее бизнес данные в связи 
    # с ошибкой чтения из Kubernetes API на шаге (не успешно выполненный шаг)
    failure = ActionObservation(
        action_id="failed-read",
        success=False,
        result=None,
        error="Kubernetes API timeout",
        observed_at=NOW,
    )

    result = evaluate_deployment_ready_replicas(
        rule,
        [
            success,
            failure,
        ],
        now=NOW,
    )
    assert result.status == "unknown"

    # Повторно прочитать Deployment {resource} после неуспешного действия
    assert result.remaining_work is not None


###############################################
# Тестирование функции проверки детерминированного правила с наблюдением несвязанного ресурса
###############################################
def test_unrelated_observation_with_same_time_is_ignored(rule):
    """
    Тестрование функции evaluate_deployment_ready_replicas() 
    сравнения значений ready и desired когда 
    наблюдение содержит бизнес данные для успешного результата проверки из верного namespace 'payments', 
    но есть еще одно наблюдение не связанное с проверяемым ресурсом из namespace 'default'.
    Последнее не связанное наблюдение должно игнорирваться при создании результата проверки.
    """

    # Наблюдение содержащее бизнес данные для passed результата проверки корректного ресурса
    related_observation = make_observation(
        ready=3,
        desired=3,
        observed_at=NOW  - timedelta(seconds=10),
        namespace="payments",
    )

    # Наблюдение содержащее бизнес данные другого ресурса, данное наблюдение должно игнорироваться на функции проверки
    unrelated_observation = make_observation(
        ready=1,
        desired=3,
        observed_at=NOW,
        namespace="default"
    )

    result = evaluate_deployment_ready_replicas(
        rule,
        [
            related_observation,
            unrelated_observation
        ],
        now = NOW,
    )
    
    assert result.status == "passed"


###############################################
# Тестирование функции evaluate_deterministic_rule() диспетчеризации
###############################################
def test_dispatcher_selects_deployment_check(rule):
    result = evaluate_deterministic_rule(
        rule,
        [
            make_observation(ready=2, desired=3)
        ],
        now=NOW,
    )

    assert result.status == "failed"




###############################################
# Тестирование десериализации JSON в класс детерминированного правила готовности deployment реплик
###############################################
def test_goal_parses_deployment_rule(rule):

    # Валидация схемы и создание объекта ЦЕЛИ
    goal = AgentGoal.model_validate(
        {
            "description": CRITERION,
            "success_criteria": [CRITERION],
            "constraints": ["Ничего не изменять"],
            "max_iterations": 3,
            "deterministic_rules": [
                rule.model_dump(mode="json"),           # <- указывааем JSON
            ],
        }
    )

    # Проверка типа данных
    assert isinstance(goal.deterministic_rules[0], DeploymentReadyReplicasRule)
