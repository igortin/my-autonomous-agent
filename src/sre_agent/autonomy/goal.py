from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from sre_agent.model import model
from sre_agent.state import AgentGoal, SREAgentState
from sre_agent.utils import get_latest_human_message


GOAL_INTERPRETER_SYSTEM_PROMPT = """
You are the Goal Interpreter of an autonomous SRE agent.

Your responsibility is to transform the latest user request into an
explicit, machine-readable AgentGoal.

The AgentGoal describes the desired final state. It is not an action plan.

Rules:

1. description

Create a concise description of the desired final state.

Describe what must become true, not which commands should be executed.

2. success_criteria

Create one or more observable and verifiable conditions.

Success criteria must be suitable for later evaluation against real
system state.

Prefer concrete fields, metrics and thresholds.

For Kubernetes workloads, distinguish desired replicas from ready replicas:

- spec.replicas represents the desired replica count;
- status.readyReplicas represents currently ready replicas.

When the user asks to restore a workload to a replica count, include both
conditions when appropriate.

3. constraints

Preserve constraints explicitly stated by the user.

Also add these default safety constraints for operational changes:

- do not modify unrelated resources;
- require human approval before write or destructive operations.

Do not invent cluster names, namespaces, environments, deadlines,
resource names or thresholds that are absent from the user request.

4. max_iterations

Use the user's requested limit when it is explicitly provided.

Otherwise use 5.

5. Separation of responsibilities

Do not create an action plan.
Do not select tools.
Do not execute commands.
Do not inspect Kubernetes.
Do not claim that the goal has already been achieved.
Do not answer the user.

Return only AgentGoal.
"""

# обертка над базовой моделью
goal_interpreter_model = model.with_structured_output(AgentGoal)


async def goal_interpreter_node(
    state: SREAgentState,
    config: RunnableConfig,
) -> dict:
    """
    Convert the latest user request into a validated AgentGoal.

    Responsibilities:
    - read the latest HumanMessage;
    - invoke the LLM with structured output;
    - validate the result as AgentGoal;
    - serialize the goal into graph state.

    Must not:
    - execute tools;
    - inspect infrastructure;
    - create an action plan;
    - mutate the environment;
    - decide whether the goal has been achieved.
    """

    try:

        # последнее сообщение пользователя
        latest_user_message = get_latest_human_message(
            state["messages"]
        )

        # Structured-output вызов LLM
        goal: AgentGoal = await goal_interpreter_model.ainvoke(
            [
                SystemMessage(
                    content=GOAL_INTERPRETER_SYSTEM_PROMPT
                ),
                latest_user_message,
            ],
            config=config,
        )

        # сохраняем dict и не зависит от внутреннего Python-типа при чтении.
        return {
            "goal": goal.model_dump(mode="json"),
            "goal_interpreter_error": None,
        }

    except Exception as exc:
        return {
            "goal": None,
            "goal_interpreter_error": {
                "type": "goal_interpreter_structured_output_error",
                "message": str(exc),
            },
        }
    