from langgraph.graph import (
    END,
    START,
    StateGraph,
)

from sre_agent.agents.planner_agent import (
    planner_agent_node,
    route_after_planner,
)
from sre_agent.autonomy.executor import executor_node
from sre_agent.autonomy.goal import goal_interpreter_node
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
from sre_agent.autonomy.replanner import replanner_node
from sre_agent.autonomy.verifier import (
    route_after_verification,
    verifier_node,
)
from sre_agent.state import SREAgentState







def build_readonly_autonomous_graph():

    builder = StateGraph(SREAgentState)

    builder.add_node(
        "goal_interpreter", 
        goal_interpreter_node
    )
    # отдельный Planner Agent
    builder.add_node(
        "planner", 
        planner_agent_node
    )

    builder.add_node(
        "initialize_lifecycle", 
        initialize_lifecycle_node
    )

    builder.add_node(
        "executor", 
        executor_node
    )

    builder.add_node(
        "observer",
        observer_node,
    )

    builder.add_node(
        "verifier",
        verifier_node,
    )

    builder.add_node(
        "advance_iteration",
        advance_iteration_node,
    )
    # отдельная replanner нода
    builder.add_node(
        "replanner",
        replanner_node,
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
    # Edge
    #------------------------------
    builder.add_edge(
        "goal_interpreter",
        "planner",
    )

    #------------------------------
    # Conditonal Edge
    #------------------------------
    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "continue": "initialize_lifecycle",
            "stop": "unrecoverable_error",
        },
    )

    #------------------------------
    # Edge
    #------------------------------
    builder.add_edge(
        "initialize_lifecycle",
        "executor",
    )

    builder.add_edge(
        "executor",
        "observer",
    )

    #------------------------------
    # Conditonal Edge
    #------------------------------
    # Маршрутизация при прверки наличия next step вexecution plan или проверка достижения цели
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
    # Edge
    #------------------------------
    # Подготовка к новой итерации lifecycle
    builder.add_edge(
        "verifier",
        "advance_iteration",
    )

    #------------------------------
    # Conditonal Edge
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
    # Edge
    #------------------------------
    # Создание нового пересмотренного плана и запуск новой итерации lifecycle 
    builder.add_edge(
        "replanner",
        "executor",
    )


    #------------------------------
    # Edge Выход
    #------------------------------
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


    # Компилирование Graph
    return builder.compile()


# Инициализация графа
readonly_autonomous_graph = build_readonly_autonomous_graph()