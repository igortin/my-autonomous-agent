from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from sre_agent.model import model
from sre_agent.state import AgentGoal, SREAgentState

from sre_agent.utils import get_latest_human_message
import traceback

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

5. deterministic_rules

Use deterministic_rules for supported formal checks.

Currently supported rule:

- kind="pod_ready": check that a specific Pod has
  status.conditions[type="Ready"].status == "True".

- kind="deployment_ready_replicas":
  check that one Deployment has
  status.ready_replicas >= spec.replicas.

For deployment_ready_replicas:
- copy criterion exactly from success_criteria;
- specify cluster_alias, namespace and deployment_name;
- use this rule only when the criterion asks whether all
  currently desired replicas are ready;
- do not use this rule for an explicit fixed replica target,
  such as "at least three ready replicas";
- do not use this rule as proof of rollout completion,
  service availability or incident resolution;
- do not invent missing resource identifiers.

For pod_ready:
- copy criterion exactly from success_criteria;
- specify cluster_alias, namespace and pod_name;
- preserve the resource identity from the user request;
- do not invent missing resource identifiers.
- Do not attach pod_ready to broader conditions such as:
    - the service is healthy;
    - the incident is resolved;
    - the root cause is established.


If the criterion is not supported by an available rule,
leave it for semantic verification.

Do not generate Python expressions or executable code.

6. Separation of responsibilities

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
    
    LLM здесь переводит запрос в контракт.

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
            "planner_input": None,
        }

    except Exception as exc:
        traceback.print_exc()

        return {
            "goal": None,
            "goal_interpreter_error": {
                "type": "goal_interpreter_structured_output_error",
                "message": str(exc),
            },
            "planner_input": None,
        }
    