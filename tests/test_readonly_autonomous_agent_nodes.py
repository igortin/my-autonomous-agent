import pytest
from unittest.mock import AsyncMock, patch
from sre_agent.autonomy.executor import executor_node

from sre_agent.autonomy.observer import observer_node


from sre_agent.autonomy import verifier 

from sre_agent.autonomy.verifier import verifier_model, verifier_node, route_after_verification

from sre_agent.state import GoalVerification

#################################
# Unit Test: Executor Run
#################################

@pytest.mark.asyncio
async def test_executor_runs_allowed_readonly_tool():

    # Создаем новый state
    state = {
        "execution_plan": {
            "steps": [
                {
                    "id": "inspect-pod",
                    "description": "Inspect pod",
                    "agent": "kubernetes",
                    "action_type": "read",
                    "tool_name": "get_pod_tool",
                    "tool_args": {
                        "cluster_name": "test-cluster",
                        "namespace": "payments",
                        "pod_name": "payment-api-1",
                    },
                    "depends_on": [],
                }
            ]
        },
        "completed_step_ids": [],
    }

    # Создаем результат
    fake_result = {
        "ok": True,
        "action": "get_pod",
        "pod": {
            "status": {
                "phase": "Running"
            }
        },
    }

    # инициализируем Tool Mock
    fake_tool = AsyncMock()

    # Настраиваем вызов Tool Mock вернет fake_result
    fake_tool.ainvoke.return_value = fake_result

    # код временно подменяет реестр READ_ONLY_TOOL_REGISTRY, запускает executor_node и после выхода из блока восстанавливает реестр.
    with patch.dict(
        "sre_agent.autonomy.executor.READ_ONLY_TOOL_REGISTRY",
        {"get_pod_tool": fake_tool},
        clear=True,
    ):
        # Вызов executor_node
        result = await executor_node(state)

    assert result["current_step"] == "inspect-pod"

    assert result["execution_error"] is None


    # Проверяем что вызвали ровно один раз и передали ему именно этот словарь в аргументе
    fake_tool.ainvoke.assert_awaited_once_with(
        {
            "cluster_name": "test-cluster",
            "namespace": "payments",
            "pod_name": "payment-api-1",
        }
    )

#################################
# Unit Test: Executor блокировка action_type write
#################################
@pytest.mark.asyncio
async def test_executor_rejects_write_action():

    # Создаем новый state
    state = {
        "execution_plan": {
            "steps": [
                {
                    "id": "restart-pod",
                    "description": "Restart pod",
                    "agent": "kubernetes",
                    "action_type": "write",                         # <---- не поддерживаемый action type на execution_node 
                    "tool_name": "restart_pod_tool",
                    "tool_args": {},
                    "depends_on": [],
                }
            ]
        },
        "completed_steps_ids": [],
    }

    result = await executor_node(state)

    assert result["execution_error"]["type"] == "forbidden_action_type"

    assert result["human_escalation_required"] is True


#################################
# Unit Test: Executor блокировка uknown tool
#################################
@pytest.mark.asyncio
async def test_executor_reject_unknow_tool():

    # Создаем новый state
    state = {
        "execution_plan": {
            "steps": [
                {
                    "id": "restart-pod",
                    "description": "Restart pod",
                    "agent": "kubernetes",
                    "action_type": "read",                         # <---- не поддерживаемый action type на execution_node 
                    "tool_name": "unknow_tool",
                    "tool_args": {},
                    "depends_on": [],
                }
            ]
        },
        "completed_steps_ids": [],
    }

    result = await executor_node(state)

    assert result["execution_error"]["type"] == "tool_not_allowed"

    assert result["human_escalation_required"] is True


#################################
# Unit Test: Observer Run
#################################
def test_observer_stores_normalized_observation():

    # Создаем новый state c результатом Tool выполения в pending_step_result
    state = {
        "observations": [],
        "completed_step_ids": [],
        "pending_step_result": {
            "step": {
                "id": "inspect-events",
                "description": "Inspect pod events",
                "agent": "kubernetes",
                "action_type": "read",
                "tool_name": "get_pod_events_tool",
                "tool_args": {},
                "depends_on": [],
            },
            "raw_result": {
                "ok": True,
                "events": [
                    {
                        "reason": "BackOff",
                        "message": (
                            "Back-off restarting failed container"
                        ),
                    }
                ],
            },
        },
    }

    # Вызов ноды Observer
    result = observer_node(state)
 
    assert result["completed_step_ids"] == ["inspect-events"]
    assert len(result["observations"]) == 1

    assert result["observations"][0]["ok"] is True
    assert result["pending_step_result"] is None


#################################
# Unit Test: Verifier Run
#################################
@pytest.mark.asyncio
async def test_verifier_marks_goal_as_reached(monkeypatch):

    # Создаем тестовый объект класса GoalVerification 
    # c ОЦЕКОЙ достаточности собранных наблюдений 
    # для достижения цели
    fake_verification = GoalVerification(
        goal_reached=True,
        satisfied_criteria=[
            "Pod state observed",
            "Logs collected",
            "Events collected",
            "Cause supported by evidence",
        ],
        missing_criteria=[],
        evidence=[
            "Container terminated with exit code 1",
            "Logs contain database connection refused",
            "Events show BackOff",
        ],
        reason=(
            "All success criteria are supported "
            "by observations."
        ),
    )

    # инициализация фейк модели 
    fake_verifier_model = AsyncMock()

    # при вызове ainvoke возращает объект expected_plan - тестовые данные fixture переданные как параметр 
    fake_verifier_model.ainvoke.return_value = fake_verification 

    # подменяем в модуле verifer.py объект verifier_model на fake_verifier_model
    monkeypatch.setattr(
        verifier,                       # Имя модуля
        "verifier_model",               # Объект который заменяют 
        fake_verifier_model,            # Объект который будет использоваться
    )

    # Создаем новый state содержащий goal и список observations требующиеся для verifier_node
    state = {
        "goal": {
            "description": "Determine why pod crashes",
            "success_criteria": [
                "Pod state observed",
                "Logs collected",
                "Events collected",
                "Cause supported by evidence",
            ],
            "constraints": [
                "Read-only actions only",
            ],
            "max_iterations": 3,
        },
        "observations": [
            {
                "step_id": "inspect-pod",
                "tool_name": "get_pod_tool",
                "ok": True,
                "summary": "Pod inspected",
                "data": {
                    "container_state": {
                        "exit_code": 1
                    }
                },
                "error": None,
            }
        ],
    }

    # Вызов ноды c входным state и получаем fake_verification
    result = await verifier_node(
        state, 
        config={},
    )

    # ТЕСТЫ
    assert result["verification"]["goal_reached"] is True

    # Потому что в fake_verification.missing_criteria пустой список
    assert result["replan_feedback"] == []



#################################
# Unit Test: route_after_verification Replan
#################################
def test_incomplete_verification_routes_to_replan():
    # Создаем новый state содержащий номер текущей итерации, 
    # максимальное количество итераций, verification по схеме GoalVerification
    # созданный на verifier_node, также ошибки на предыдцщих нодах
    state = {
        "iteration_count": 1,
        "max_iterations": 3,
        "verification": {
            "goal_reached": False,                      # <-- поэтому требуется replan 
            "satisfied_criteria": [
                "Pod state observed",
            ],
            "missing_criteria": [
                "Recent logs are missing",
                "Related events are missing",
            ],
            "evidence": [],
            "reason": "Insufficient evidence",
        },
        "execution_error": None,
        "human_escalation_required": False,
    }

    # Определяем маршрута
    route = route_after_verification(state)

    # ТЕСТ
    assert route == "replan"



#################################
# Unit Test: route_after_verification - Тест успеха на последней итерации
#################################
def test_goal_reached_wins_on_last_iteration():

    # Создаем новый state содержащий номер текущей итерации, 
    # максимальное количество итераций, verification по схеме GoalVerification 
    # созданный на verifier_node, также ошибки на предыдцщих нодах
    state = {
        "iteration_count": 3,
        "max_iterations": 3,
        
        "verification": {
            "goal_reached": True,                            # <-- достигли цели
            "satisfied_criteria": ["all"],
            "missing_criteria": [],
            "evidence": ["sufficient evidence"],
            "reason": "Goal reached",
        },
        
        "execution_error": None,
        "human_escalation_required": False,
    }

    # Определяем маршрут
    route = route_after_verification(state)


    # ТЕСТ
    assert route == "goal_reached"
