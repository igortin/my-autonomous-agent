from langchain_core.tools import tool

from sre_agent.state import SREAgentState

from langgraph.graph import END, START, StateGraph

from sre_agent.autonomy.executor import executor_node
from sre_agent.autonomy import executor

from sre_agent.autonomy.lifecycle import (
    advance_iteration_node,
    goal_reached_node,
    human_escalation_node,
    initialize_lifecycle_node,
    max_iterations_reached_node,
    unrecoverable_error_node,
)
from sre_agent.autonomy.observer import (
    observer_node,
    route_after_observer,
)
from sre_agent.autonomy.verifier import (
    route_after_verification,
)

import pytest

from langchain_core.messages import HumanMessage

#########################################
# Tools
#########################################

# Декоратор @tool
@tool
def fake_get_pod_tool(
    cluster_alias: str,
    namespace: str,
    pod_name: str,
) -> dict:
    """
    Return fake Kubernetes pod information.
    """

    return {
        "ok": True,
        "action": "get_pod",
        "cluster_alias": cluster_alias,
        "namespace": namespace,
        "pod": {
            "name": pod_name,
            "phase": "Running",
            "container_statuses": [
                {
                    "name": "payment-api",
                    "ready": False,
                    "restart_count": 5,
                    "state": {
                        "waiting": {
                            "reason": "CrashLoopBackOff",
                        }
                    },
                    "last_state": {
                        "terminated": {
                            "exit_code": 1,
                            "reason": "Error",
                        }
                    },
                }
            ],
        },
    }


@tool
def fake_get_pod_logs_tool(
    cluster_alias: str,
    namespace: str,
    pod_name: str,
    tail_lines: int = 20,
) -> dict:
    """
    Return fake Kubernetes pod logs.
    """

    return {
        "ok": True,
        "action": "get_pod_logs",
        "cluster_alias": cluster_alias,
        "namespace": namespace,
        "pod_name": pod_name,
        "logs": (
            "ERROR: database connection refused\n"
            "Application terminated with exit code 1"
        ),
    }


@tool
def fake_get_pod_events_tool(
    cluster_alias: str,
    namespace: str,
    pod_name: str,
) -> dict:
    """
    Return fake Kubernetes pod events.
    """

    return {
        "ok": True,
        "action": "get_pod_events",
        "cluster_alias": cluster_alias,
        "namespace": namespace,
        "pod_name": pod_name,
        "events": [
            {
                "type": "Warning",
                "reason": "BackOff",
                "message": (
                    "Back-off restarting failed container "
                    "payment-api"
                ),
            }
        ],
    }




#########################################
# Fake Goal Interpreter
#########################################
async def fake_goal_interpreter_node(
    state: SREAgentState,
) -> dict:

    return {
        "goal": {
            "description": (
                "Determine why payment-api pod is "
                "in CrashLoopBackOff"
            ),
            "success_criteria": [
                "Current pod state is observed",
                "Recent container logs are collected",
                "Related Kubernetes events are collected",
                "Likely cause is supported by evidence",
            ],
            "constraints": [
                "Use read-only Kubernetes actions only",
                "Do not modify Kubernetes resources",
            ],
            "max_iterations": 3,
        },
        "goal_interpreter_error": None,
    }




#########################################
# Fake Planner
#########################################
async def fake_planner_node(
    state: SREAgentState,
) -> dict:
    """
    Первая версия плана намеренно не содержит get_pod_events_tool
    """
    return {
        "execution_plan": {
            "steps": [
                {
                    "id": "inspect-pod",
                    "description": (
                        "Inspect current pod status"
                    ),
                    "agent": "kubernetes",
                    "action_type": "read",
                    "action": {
                        "action_id": "read-pod-status",
                        "tool": "get_pod_tool",
                        "arguments": {
                            "cluster_alias": "test-cluster",
                            "namespace": "payments",
                            "pod_name": "payment-api-1",
                        },
                        "expected_result": "Obtain current pod status.",
                        "risk_level": "read",
                    },
                    "depends_on": [],
                },
                {
                    "id": "inspect-logs",
                    "description": (
                        "Read recent container logs"
                    ),
                    "agent": "kubernetes",
                    "action_type": "read",
                    "action": {
                        "action_id": "read-pod-logs",
                        "tool": "get_pod_logs_tool",
                        "arguments": {
                            "cluster_alias": "test-cluster",
                            "namespace": "payments",
                            "pod_name": "payment-api-1",
                            "tail_lines": 20,
                        },
                        "expected_result": "Obtain recent container logs.",
                        "risk_level": "read",
                    },
                    "depends_on": [
                        "inspect-pod",
                    ],
                },
            ]
        },
        "current_step": None,
        "planner_error": None,
    }


#########################################
# Fake Verifier
#########################################
async def fake_verifier_node(
    state: SREAgentState,
) -> dict:

    """
    Нода Verifier должна проверить недостаточость собранных данных 
    поскольку в первичном плане не вызывался tool_name get_pod_events_tool
    и выполнить переплаирование на Replanner
    """
    # Читаем список объектов класса StepObservation
    observations = state.get(
        "observations",
        [],
    )

    # Создаем множество из выполненых Tool шагов
    observed_tools = {
        observation["tool_name"]
        for observation in observations
    }

    # Создаем множество из необходимых шагов
    required_tools = {
        "get_pod_tool",
        "get_pod_logs_tool",
        "get_pod_events_tool",
    }

    # Проверяем разность множеств
    missing_tools = (
        required_tools - observed_tools
    )

    # Проверка наличия missing_tools, что значит не все required tools были запущены
    if missing_tools:
        return {
            "verification": {
                "goal_reached": False,
                "satisfied_criteria": [
                    "Current pod state is observed",
                    "Recent container logs are collected",
                ],
                "missing_criteria": [
                    "Related Kubernetes events are missing",
                ],
                "evidence": [
                    "Pod is in CrashLoopBackOff",
                    (
                        "Application logs contain "
                        "database connection refused"
                    ),
                ],
                "reason": (
                    "Pod state and logs were collected, "
                    "but Kubernetes events are missing."
                ),
            },
            "replan_feedback": [
                "Collect Kubernetes events for the pod"
            ],
        }

    return {
        "verification": {
            "goal_reached": True,
            "satisfied_criteria": [
                "Current pod state is observed",
                "Recent container logs are collected",
                "Related Kubernetes events are collected",
                "Likely cause is supported by evidence",
            ],
            "missing_criteria": [],
            "evidence": [
                "Pod is in CrashLoopBackOff",
                (
                    "Container terminated with "
                    "exit code 1"
                ),
                (
                    "Logs contain database "
                    "connection refused"
                ),
                (
                    "Kubernetes events contain "
                    "BackOff"
                ),
            ],
            "reason": (
                "All success criteria are supported "
                "by collected observations."
            ),
        },
        "replan_feedback": [],
    }


#########################################
# Fake Replanner
#########################################
async def fake_replanner_node(
    state: SREAgentState,
) -> dict:
    return {
        "execution_plan": {
            "steps": [
                {
                    "id": "inspect-events",
                    "description": (
                        "Collect Kubernetes events "
                        "for the failing pod"
                    ),
                    "agent": "kubernetes",
                    "action_type": "read",
                    "action": {
                        "action_id": "read-pod-events",
                        "tool": "get_pod_events_tool",
                        "arguments": {
                            "cluster_alias": "test-cluster",
                            "namespace": "payments",
                            "pod_name": "payment-api-1",
                        },
                        "expected_result": "Obtain Kubernetes events for the pod.",
                        "risk_level": "read",
                    },
                    "depends_on": [],
                }
            ]
        },

        # Обнуляем  completed шаги для нового плана.
        "completed_step_ids": [],

        "current_step": None,
        "planner_error": None,
    }




#########################################
#  Fake Graph
#########################################
def build_test_autonomous_graph():
    builder = StateGraph(SREAgentState)

    builder.add_node(
        "goal_interpreter",
        fake_goal_interpreter_node,
    )
    builder.add_node(
        "planner",
        fake_planner_node,
    )
    builder.add_node(
        "initialize_lifecycle",
        initialize_lifecycle_node,
    )
    builder.add_node(
        "executor",
        executor_node,
    )
    builder.add_node(
        "observer",
        observer_node,
    )
    builder.add_node(
        "verifier",
        fake_verifier_node,
    )
    builder.add_node(
        "advance_iteration",
        advance_iteration_node,
    )
    builder.add_node(
        "replanner",
        fake_replanner_node,
    )

    builder.add_node(
        "goal_reached",
        goal_reached_node,
    )
    builder.add_node(
        "max_iterations_reached",
        max_iterations_reached_node,
    )
    builder.add_node(
        "unrecoverable_error",
        unrecoverable_error_node,
    )
    builder.add_node(
        "human_escalation",
        human_escalation_node,
    )

#------------------------------
# START
#------------------------------
    builder.add_edge(
        START,
        "goal_interpreter",
    )

#------------------------------
# EDGE
#------------------------------
    builder.add_edge(
        "goal_interpreter",
        "planner",
    )

    builder.add_edge(
        "planner",
        "initialize_lifecycle",
    )

    builder.add_edge(
        "initialize_lifecycle",
        "executor",
    )

    builder.add_edge(
        "executor",
        "observer",
    )

#------------------------------
# CE
#------------------------------
    builder.add_conditional_edges(
        "observer",
        route_after_observer,
        {
            "execute_next_step": "executor",
            "verify_goal": "verifier",
            "stop": "unrecoverable_error",
        },
    )

#------------------------------
# EDGE
#------------------------------
    builder.add_edge(
        "verifier",
        "advance_iteration",
    )

#------------------------------
# CE
#------------------------------
    builder.add_conditional_edges(
        "advance_iteration",
        route_after_verification,
        {
            "goal_reached": "goal_reached",
            "replan": "replanner",
            "max_iterations_reached":
                "max_iterations_reached",
            "unrecoverable_error":
                "unrecoverable_error",
            "human_escalation_required":
                "human_escalation",
        },
    )

#------------------------------
# EDGE
#------------------------------
    builder.add_edge(
        "replanner",
        "executor",
    )

    builder.add_edge(
        "goal_reached",
        END,
    )
    builder.add_edge(
        "max_iterations_reached",
        END,
    )
    builder.add_edge(
        "unrecoverable_error",
        END,
    )
    builder.add_edge(
        "human_escalation",
        END,
    )

    return builder.compile()



#########################################
#  Интеграционный Тест
#########################################
@pytest.mark.asyncio
async def test_complete_autonomous_loop_without_kubernetes(
    monkeypatch,
):
    """
    Тестирование выполненеия fake графа в 2-е итерации lifecycle по execution_plan на каждой интерации.

    Execution Plan 1 - Итерация 1
    -------------
    inspect-pod
        ↓
    inspect-logs
        ↓
    Execution Plan 2 - Итерация 2
    -------------
    inspect-events
    """

    # Опредлить маппинг Tools
    fake_tool_registry = {
        "get_pod_tool": fake_get_pod_tool,
        "get_pod_logs_tool": fake_get_pod_logs_tool,
        "get_pod_events_tool": fake_get_pod_events_tool,
    }

    # Настройка подмены
    monkeypatch.setattr(
        executor,                               # имя модуля
        "READ_ONLY_TOOL_REGISTRY",              # объект который подменяем
        fake_tool_registry,                     # объект которым заменяем
    )

    # Инициализируем Fake Graph
    graph = build_test_autonomous_graph()

    # Определяем первичный state
    initial_state = {
            "messages": [
                HumanMessage(
                    content=(
                        "Определи причину CrashLoopBackOff "
                        "для payment-api-1"
                    )
                )
            ]
        }


    # Вызов Fake Graph
    result = await graph.ainvoke(
        initial_state,
        config={
             "recursion_limit": 50,
        },
    )


    # ТЕСТЫ
    assert result["termination_reason"] == "goal_reached"

    assert result["iteration_count"] == 2

    assert result["max_iterations"] == 3

    assert result["verification"]["goal_reached"] is True

    assert result["verification"]["missing_criteria"] == []

    observations = result["observations"]

    assert len(observations) == 3

    assert [observation["step_id"] for observation in observations] == ["inspect-pod", "inspect-logs", "inspect-events"]

    assert [observation["tool_name"] for observation in observations] == ["get_pod_tool", "get_pod_logs_tool", "get_pod_events_tool"]

    assert all(observation["ok"] for observation in observations)

    # После replanning в state остаются completed steps
    # только текущего, второго плана.
    assert result["completed_step_ids"] == ["inspect-events"]

    assert result.get("execution_error") is None

    assert result.get("human_escalation_required", False) is False
    # print(result)