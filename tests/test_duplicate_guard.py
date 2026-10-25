from sre_agent.state import AgentAction
from sre_agent.autonomy.duplicate_guard import (
    build_action_attempt,
    build_action_fingerprint,
    deployment_state_projection,
    is_duplicate_limit_reached,
    stable_hash,
)

""" Unit-тесты чистых функций """

##############################################
# Тестовые данные Намерение в PlanStep.action
##############################################
def make_action(action_id: str) -> AgentAction:
    return AgentAction(
        action_id=action_id,
        tool="get_deployment_tool",
        arguments={
            "cluster_alias": "docker-desktop",
            "namespace": "payments",
            "deployment_name": "payment-api",
        },
        expected_result="Получить состояние Deployment",
        risk_level="read",
    )


############################################
#  Тестирование вспомогательной функции build_action_fingerprint()
############################################
def test_new_action_id_does_not_change_fingerprint():
    """
    Тестирование функции build_action_fingerprint() 
    на создания отпечатков fingerprint Попыток вызова инстурментов 
    и игнорирванием полей action.id
    """

    # Первое намерение действия
    first = make_action("action-1")
    # Второе намерение действия
    second = make_action("action-2")

    # Проверка строки отпечатки равны при разных action.id
    assert build_action_fingerprint(first, first.arguments) == build_action_fingerprint(second, second.arguments)


############################################
#  Тестирование вспомогательной функции stable_hash()
############################################
def test_dictionary_key_order_does_not_matter():
    """
        Тестирование функции stable_hash()на генерацию хеш значения
        вне зависимости от очереднсти элементов в обьекте.
        Ключ: sort_keys=True
    """
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})


############################################
#  Тестирование вспомогательной функции build_action_fingerprint()
############################################
def test_different_arguments_change_fingerprint():
    """ 
    Тестирование функции build_action_fingerprint() и генерацию разных отпечатков 
    fingerprint попыток вызова инструмента при разных вводных аргументах
    """

    # Создаем намерение AgentAction
    action = make_action("action-1")

    # Создаем новый normalized_arguments  
    other_arguments = {
        **action.arguments,
        "namespace": "another-namespace",
    }

    assert build_action_fingerprint(action, action.arguments) != build_action_fingerprint(action, other_arguments)

############################################
# Тестирование вспомогательной функции is_duplicate_limit_reached()
############################################
def test_third_attempt_with_same_key_is_blocked():
    """
    Тестирование функции проверки на ограничение количества ActionAttempt попыток вызова инструментов.  
    """
    # Создаем намерение AgentAction
    action = make_action("action-1")

    # Создаем Попытку ActionAttempt
    candidate = build_action_attempt(
        action=action,
        normalized_arguments=action.arguments,
        environment_fingerprint="state-S",
    )

    # Сериализуем обьект ActionAttempt в dict
    record = candidate.model_dump(mode="json")

    #  Проверка количества попыток меньше max_attempts
    assert not is_duplicate_limit_reached(candidate=candidate, attempts=[record], max_attempts=2)

    #  Проверка количества попыток равно max_attempts
    assert is_duplicate_limit_reached(candidate=candidate, attempts=[record, record], max_attempts=2,)




############################################
# Тестирование вспомогательной функции is_duplicate_limit_reached()
############################################
def test_changed_environment_allows_another_attempt():
    """
    Тестирование функции - ограничения на количество попыток вызова инструментов не блокирует 
    выполнение попытки ActionAttempt при разных состояниях одного итого же Deployment ресурса.
    Поскольку происходит вобьекте ActionAttempt проверка ключа duplicate_key.
    """
    
    # Создаем намерение AgentAction
    action = make_action("action-1")

    # Создаем предыдущую Попытку ActionAttempt на основе action
    previous_attempt = build_action_attempt(
        action=action,
        normalized_arguments=action.arguments,
        environment_fingerprint="state-previous",
    )

     # Сериализуем обьект ActionAttempt в dict
    previous_attempt_record = previous_attempt.model_dump(mode="json")


    # Создаем новую Попытку ActionAttempt на основе того же action
    candidate_attempt = build_action_attempt(
        action=action,
        normalized_arguments=action.arguments,
        environment_fingerprint="state-current",
    )

    assert not is_duplicate_limit_reached(
        candidate=candidate_attempt,
        attempts=[previous_attempt_record, previous_attempt_record],
        max_attempts=2,
    )


#############################################
# Тестирование вспомогательной функции deployment_state_projection()
#############################################
def test_resource_version_does_not_change_projection():
    """
    Тестирование функции на создание идентичных Deployment представлений
    при получении разных значений resource_version в результате выполнения Tool.
    """
    # Функция Mock создания результата выполнения Tool
    def mock_tool_result(resource_version: str) -> dict:
        return {
            "deployment": {
                "metadata": {
                    "uid": "deployment-uid",
                    "generation": 7,
                    "resource_version": resource_version,
                },
                "spec": {"replicas": 3},
                "status": {
                    "observed_generation": 7,
                    "ready_replicas": 1,
                },
            }
        }

    assert deployment_state_projection(mock_tool_result("100")) == deployment_state_projection(mock_tool_result("101"))