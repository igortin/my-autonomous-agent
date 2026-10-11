import pytest

from sre_agent.autonomy.verifier import (
    route_after_verification,
)

# Подготовка тестовых входных параметров
@pytest.mark.parametrize(
    "iteration_count, goal_reached, expected",
    [
        (1, False, "replan"),
        (3, False, "max_iterations_reached"),
        (3, True, "goal_reached"),
    ],
)

def test_route_after_verification(
    iteration_count,
    goal_reached,
    expected,
):



    state = {
        "iteration_count": iteration_count,
        "max_iterations": 3,
        "verification": {
            "goal_reached": goal_reached,
        },
    }

    assert route_after_verification(state) == expected



def test_verifier_error_stops_lifecycle():

    """ Тестирование остановки выполнения итерации lifecycle"""
    state = {
        "iteration_count": 1,
        "max_iterations": 3,
        "verification": None,
        "execution_error": {
            "type": "verifier_error",
            "message": "Invalid verification response",
        },
    }

    assert route_after_verification(state) == "unrecoverable_error"