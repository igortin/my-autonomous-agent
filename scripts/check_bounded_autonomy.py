from sre_agent.autonomy.lifecycle import (
    advance_iteration_node,
    route_autonomous_lifecycle,
)


"""
Тестируем route маршритузацию lifecycle.
Путем синтетического обновления состояния state.iteration_count, 
при каждом вызове helper функции ноды advance_iteration_node
и сравнения текущего iteration_count значения атрибута с state.max_iterations 
при вызове ноды route_autonomous_lifecycle.
"""

state = {
    "iteration_count": 0,
    "max_iterations": 3,
    "termination_reason": None,
    "human_escalation_required": False,
    "rca_quality_check": {
        "needs_more_data": True,
    },
}

while True:

    state.update(
        advance_iteration_node(state)
    )

    route = route_autonomous_lifecycle(state)

    print(
        {
            "iteration_count": state["iteration_count"],
            "max_iterations": state["max_iterations"],
            "route": route,
        }
    )

    if route != "continue":
        break