from langgraph.graph import END, START, StateGraph

from sre_agent.state import SREAgentState

from sre_agent.autonomy.goal import (
    goal_interpreter_node,
)

from sre_agent.agents.planner_agent import (
    planner_agent_node,
    route_after_planner,
)

from sre_agent.autonomy.lifecycle import (
    advance_iteration_node,
    goal_reached_node,
    human_escalation_node,
    initialize_lifecycle_node,
    max_iterations_reached_node,
    unrecoverable_error_node,
)

from sre_agent.autonomy.executor import executor_node

from sre_agent.autonomy.observer import observer_node, route_after_observer

from sre_agent.autonomy.verifier import verifier_node, route_after_verification
from sre_agent.autonomy.replanner import (
    replanner_node,
    route_after_replanner,
)

###################################################
## GRAPH
###################################################
def build_graph():

    builder = StateGraph(SREAgentState)

    # -------------------------
    # Nodes
    # -------------------------
    builder.add_node(
        "goal_interpreter_node",
        goal_interpreter_node,
    )

    builder.add_node(
        "planner_agent_node",
        planner_agent_node,
    )

    builder.add_node(
        "initialize_lifecycle_node",
        initialize_lifecycle_node,
    )

    builder.add_node(
        "executor_node",
        executor_node,
    )

    builder.add_node(
        "observer_node",
        observer_node,
    )

    builder.add_node(
        "verifier_node",
        verifier_node,
    )


    builder.add_node(
        "advance_iteration_node",
        advance_iteration_node,
    )


    builder.add_node(
        "replanner_node",
        replanner_node,
    )

    builder.add_node(
        "goal_reached_node",
        goal_reached_node,
    )

    builder.add_node(
        "max_iterations_reached_node",
        max_iterations_reached_node,
    )

    builder.add_node(
        "unrecoverable_error_node",
        unrecoverable_error_node,
    )

    builder.add_node(
        "human_escalation_node",
        human_escalation_node,
    )

    # -------------------------
    # START
    # -------------------------

    builder.add_edge(
        START,
        "goal_interpreter_node",
    )

    # -------------------------
    # Edges
    # -------------------------
    builder.add_edge(
        "goal_interpreter_node",
        "planner_agent_node",
    )

    #------------------------------
    # CE
    #------------------------------
    builder.add_conditional_edges(
        "planner_agent_node",
        route_after_planner,
        {
            "continue": "initialize_lifecycle_node",
            "stop": "unrecoverable_error_node",
        },
    )

   # -------------------------
    # Edges
    # -------------------------
    builder.add_edge(
        "initialize_lifecycle_node",
        "executor_node",
    )

    builder.add_edge(
        "executor_node",
        "observer_node",
    )

    #------------------------------
    # CE
    #------------------------------

    builder.add_conditional_edges(
        "observer_node",
        route_after_observer,
        {
            "execute_next_step": "executor_node",
            "verify_goal": "verifier_node",
            "stop": "unrecoverable_error_node",
        },
    )


    #------------------------------
    # EDGE
    #------------------------------
    builder.add_edge(
        "verifier_node",
        "advance_iteration_node",
    )

    #------------------------------
    # CE
    #------------------------------
    builder.add_conditional_edges(
        "advance_iteration_node",
        route_after_verification,
        {
            "goal_reached": "goal_reached_node",
            "replan": "replanner_node",
            "max_iterations_reached":
                "max_iterations_reached_node",
            "unrecoverable_error":
                "unrecoverable_error_node",
            "human_escalation_required":
                "human_escalation_node",
        },
    )
   
    #------------------------------
    # CE
    #------------------------------
    builder.add_conditional_edges(
        "replanner_node",
        route_after_replanner,
        {
            "continue": "executor_node",
            "stop": "unrecoverable_error_node",
        },
    )
    
    # -------------------------
    # Edge завершение при не достуижении цели
    # -------------------------

    builder.add_edge(
            "goal_reached_node",
            END,
        )

    builder.add_edge(
            "max_iterations_reached_node",
            END,
        )
    builder.add_edge(
            "unrecoverable_error_node",
            END,
        )

    builder.add_edge(
            "human_escalation_node",
            END,
        )

    # -------------------------
    #  Graph
    # -------------------------

    # LangGraph сохраняет checkpoints на boundaries graph execution
    return  builder.compile()

# Вызываемый Объект указанный в langgraph.json
graph = build_graph()