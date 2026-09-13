from langgraph.graph import END, START, StateGraph

from sre_agent.state import SREAgentState, SupervisorDecision, RCAQualityCheck, IncidentContext
from sre_agent.agents.kubernetes_agent import (
    kubernetes_agent_subgraph,
)

from sre_agent.agents.memory_agent import (
    memory_agent_subgraph,
)

from sre_agent.agents.runbook_agent import (
    runbook_agent_node,
)

from sre_agent.agents.chat_agent import (
    chat_agent_node,
)

from sre_agent.model import (
    model,
)

from sre_agent.utils import get_latest_human_message

from langgraph.store.base import BaseStore

# Across THREAD Memory
from langgraph.store.memory import InMemoryStore

# THREAD Memory
from langgraph.checkpoint.memory import MemorySaver


from langchain_core.runnables import RunnableConfig

from langchain_core.messages import merge_message_runs, HumanMessage, SystemMessage, AIMessage, ToolMessage

from pydantic import BaseModel, Field, ValidationError, ConfigDict, model_validator

from typing import TypedDict, Literal, Optional, Any, Annotated

import sys, json, yaml, re
from textwrap import dedent
from langgraph.types import Send, interrupt, Command


###################################################
## supervisor MODEL
###################################################

supervisor_model = model.with_structured_output(SupervisorDecision)



###################################################
## evaluator MODEL
###################################################
evaluator_model = model.with_structured_output(RCAQualityCheck)



###################################################
## Класс FinalRCA для `aggregate_findings_node`
###################################################

class FinalRCA(BaseModel):
    """
    Final user-facing RCA synthesized from IncidentContext.

    This is a synthesis model.

    It must not perform diagnostics or invent evidence.
    """

    model_config = ConfigDict(extra="forbid")

    title: str

    # факты
    evidence: list[str] = Field(
        default_factory=list
    )

    # предположения
    assumptions: list[str] = Field(
        default_factory=list
    )

    # наиболее вероятный вывод
    likely_root_cause: str | None = None

    contributing_factors: list[str] = Field(
        default_factory=list
    )

    # команды проверки
    commands: list[str] = Field(
        default_factory=list
    )

    recommended_actions: list[str] = Field(
        default_factory=list
    )

    confidence: Literal[
        "low",
        "medium",
        "high",
    ]

    limitations: list[str] = Field(
        default_factory=list
    )

    # Business / technical impact of the incident
    impact: str | None = None


###################################################
## final_rca MODEL
###################################################
final_rca_model = model.with_structured_output(FinalRCA)





###################################################
## HELPER render_final_rca
###################################################

def render_final_rca(rca: FinalRCA) -> str:
    """
    Helper function return RCA in Markdown.
    """

    def render_list(items: list[str], empty_text: str,) -> str:
        if not items:
            return f"- {empty_text}"

        return "\n".join(f"- {item}" for item in items)


    root_cause = (
        rca.likely_root_cause
        if rca.likely_root_cause
        else "Root cause remains unconfirmed."
    )

    return dedent(
        f"""
        # RCA: {rca.title}

        ## Impact
        {rca.impact}

        ## Evidence
        {
            render_list(rca.evidence, "No concrete evidence available.")
        }

        ## Assumptions
        {
            render_list(rca.assumptions, "No additional assumptions required.")
        }

        ## Likely root cause
        {root_cause}

        ## Contributing factors
        {
            render_list(rca.contributing_factors, "No contributing factors identified.")
        }

        ## Recommended commands
        {
            render_list(rca.commands, "No commands recommended.")
        }

        ## Recommended actions
        {
            render_list(rca.recommended_actions, "No actions recommended.")
        }

        ## Confidence
        `{rca.confidence}`

        ## Limitations
        {
            render_list(rca.limitations, "No significant limitations identified.")
        }
        """
    ).strip()



###################################################
## supervisor_node SYSTEM PROMPT
###################################################
SUPERVISOR_SYSTEM_PROMPT = """
You are the supervisor of a multi-agent SRE assistant.

Analyze the latest user request and select every specialist agent
required to fully complete it.

Available specialist agents:

1. kubernetes

Use this specialist for current Kubernetes inspection and diagnostics:
- pods;
- deployments;
- services;
- namespaces;
- nodes;
- events;
- container logs;
- live cluster state.

2. memory

Use this specialist for long-term user-specific memory operations.

Select memory when the request requires:
   - reading previously saved user profile information;
   - reading or updating project information;
   - reading or updating Kubernetes cluster context;
   - saving new durable facts that should persist across conversations.


Supported long-term memory domains:
   - profile
   - projects
   - clusters

Do NOT select memory for:
   - operational runbooks;
   - temporary troubleshooting context;
   - live Kubernetes diagnostics;
   - incident report generation.

Runbooks are handled by the runbook specialist and are not part of long-term memory.

3. runbook

Use runbook specialist when the request contains
an operational symptom, failure mode, or known
troubleshooting scenario for which existing
operational guidance may be useful.

Runbook does not inspect live Kubernetes state.
It only retrieves relevant operational guidance.

4. chat

Use this specialist for plain conversational turns that do not
require live Kubernetes inspection, runbook lookup, or a long-term
memory read/write.

Examples: greetings, small talk, general non-actionable questions,
questions about the assistant itself.

chat is always selected alone. Never combine chat with kubernetes,
memory, or runbook in the same execution plan.


Selection rules:

- Select every specialist required to complete the entire request.
- A simple request may require one specialist.
- A compound request may require several specialists.
- Select kubernetes when live Kubernetes cluster state must be inspected.
- Select runbook when known troubleshooting guidance is useful.
- For troubleshooting requests containing a known symptom such as
  CrashLoopBackOff, ImagePullBackOff or Pending, select both
  kubernetes and runbook when live diagnosis is requested.
- If the user asks only for generic troubleshooting steps and does
  not request live cluster inspection, select runbook without kubernetes.
- Select chat only when the request needs none of kubernetes, memory,
  or runbook. Never combine chat with any other specialist.
- Do not call tools.
- Do not answer the user.
- Do not perform diagnostics.
- Return only SupervisorDecision.

Examples:

User:
"Запомни, что кластер bcloud-k8s-colvir-test-csko-1
использует namespace colvir-instance по умолчанию."

Decision:
required_agents = [
    "memory"
]

Example:

User:
"Проверь состояние pod payment-api
в моём сохранённом Kubernetes кластере."

Decision:
required_agents = [
    "memory",
    "kubernetes",
]

User:
"Как диагностировать CrashLoopBackOff?"

Decision:
required_agents = [
    "runbook"
]

User:
"Проверь pod payment-api с CrashLoopBackOff."

Decision:
required_agents = [
    "kubernetes",
    "runbook",
]

User:
"Проверь состояние pod payment-api."

Decision:
required_agents = ["kubernetes"]

User:
"Проверь pod payment-api с CrashLoopBackOff и подготовь RCA."

Decision:
required_agents = [
    "kubernetes",
    "runbook",
]

User:
"Привет! Как дела?"

Decision:
required_agents = [
    "chat"
]

REPLANNING RULES

You may be invoked more than once for the same user request.

When previous IncidentContext and evaluator feedback are provided,
this is an additional investigation round.

In that case:

- inspect what evidence has already been collected;
- inspect which evidence the evaluator says is missing;
- select only specialists useful for obtaining the missing evidence;
- do not blindly repeat the previous execution plan;
- avoid requesting evidence that already exists;
- use the evaluator feedback as guidance, not as unquestionable truth.
"""

###################################################
## RCA evaluator SYSTEM PROMPT
###################################################

RCA_EVALUATOR_SYSTEM_PROMPT="""
You are the quality evaluator of a production SRE incident-analysis system.

Your task is to evaluate whether the collected IncidentContext contains
enough trustworthy information to proceed to RCA synthesis.

You must evaluate only the provided IncidentContext.

Do not invent evidence.
Do not perform Kubernetes diagnostics.
Do not call tools.
Do not write the final RCA.
Do not answer the user.

Evaluation rules:

1. has_evidence

Set true only when the context contains concrete observations,
for example:

- Kubernetes object states;
- container termination reasons;
- restart counts;
- logs;
- events;
- resource usage;
- configuration values;
- other directly observed diagnostic facts.

Generic troubleshooting advice is not evidence.

2. has_clear_root_cause

Set true only when the collected evidence supports a specific
root cause with reasonable confidence.

A symptom such as:

- CrashLoopBackOff;
- Pending;
- ImagePullBackOff

is not by itself a root cause.

If only hypotheses are available, set false.

3. has_next_actions

Set true when the context contains concrete investigation or
remediation actions that can be performed next.

4. needs_more_data

Set true when more diagnostic evidence is required before a
trustworthy RCA can be produced.

Normally needs_more_data should be true when:

- no concrete evidence exists;
- the root cause remains unsupported;
- important Kubernetes diagnostic data is missing;
- specialist errors prevented evidence collection.

5. missing_evidence

When needs_more_data is true, list the concrete categories
of evidence that are still required.

Examples:

- pod logs;
- Kubernetes events;
- container previous logs;
- dependency health;
- PostgreSQL connectivity;
- node resource pressure;
- application configuration.

Do not request data that is already present in IncidentContext.


6. evaluation_summary

Briefly explain why the current evidence is sufficient
or insufficient.

The summary will be consumed by the supervisor during
the next investigation round.


Do not require absolute certainty.

The goal is enough evidence for a defensible RCA, not perfect knowledge.

Return only RCAQualityCheck.

IncidentContext:

<incident_context>
{incident_context}
</incident_context>
"""

###################################################
##  final_rca_node System Prompt 
###################################################

FINAL_RCA_SYSTEM_PROMPT = """
You are the final RCA synthesis agent of a production SRE
multi-agent incident investigation system.

Your task is to create a concise and defensible Root Cause Analysis
using only the supplied IncidentContext and RCAQualityCheck.

You are a synthesis agent.

You must NOT:

- call Kubernetes tools;
- inspect the cluster;
- call other agents;
- invent evidence;
- invent logs;
- invent Kubernetes events;
- invent timestamps;
- turn assumptions into facts.


The investigation phase has already been completed.

SOURCE OF TRUTH

Use only:

1. IncidentContext
2. RCAQualityCheck
3. The original user request

IMPACT RULES:

- Populate `impact` with the observed or strongly supported technical/business effect of the incident.
- Do not invent business impact that is not supported by evidence.
- If impact cannot be determined, return null.
- Keep impact separate from root cause.


EVIDENCE

Evidence must contain only concrete observations collected
by specialists.

Examples:

- pod status;
- restart count;
- container exit code;
- termination reason;
- Kubernetes events;
- application logs;
- previous container logs;
- configuration values.

Runbook recommendations are NOT evidence.


ASSUMPTIONS

Clearly separate assumptions from evidence.

Use assumptions when a conclusion is plausible but not directly
confirmed by collected evidence.


LIKELY ROOT CAUSE

Select the most likely root cause supported by the evidence.

If evidence does not support a reliable root cause, say that the
root cause remains unconfirmed.

Never report CrashLoopBackOff itself as the root cause.
CrashLoopBackOff is a symptom.


COMMANDS

Provide safe diagnostic or remediation commands derived from
the collected evidence and runbook guidance.

Prefer read-only diagnostic commands.

Do not claim that commands have already been executed.


CONFIDENCE

high:
root cause is directly supported by concrete evidence.

medium:
evidence strongly suggests the cause but some confirmation is missing.

low:
multiple plausible hypotheses remain.

LIMITATIONS

Explicitly mention missing evidence when relevant.


IncidentContext:

<incident_context>
{incident_context}
</incident_context>

RCAQualityCheck:

<quality_check>
{quality_check}
</quality_check>

Return only FinalRCA.

"""



###################################################
## Node supervisor_node
###################################################

async def supervisor_node(state: SREAgentState, config: RunnableConfig, store: BaseStore):
    """
    Node: supervisor_node

    Responsibility:
    - inspect the latest user request;
    - determine all required specialist agents;
    - store the execution plan in graph state;
    - store a concise explanation;
    - handle structured-output validation errors.

    The node must not:
    - answer the user;
    - append AIMessage;
    - call tools;
    - execute specialist agents;
    - update long-term memory;
    - perform Kubernetes diagnostics;
    - generate an RCA.
    """
    try:


        # Получаем пользовательский запрос
        last_user_message = get_latest_human_message(state["messages"])

        # Получаем значение какой раунд исследования
        retry_count=state.get("evaluation_retry_count", 0)

        # Формируем запрос в LLM
        supervisor_messages = [
            SystemMessage(
                content=SUPERVISOR_SYSTEM_PROMPT
            ),
            last_user_message,
        ]

        # Если это очередной раунд исследования то формируем контекст с IncidentContext (из ноды aggregate_findings_node) из предыдущих раундов
        if retry_count > 0:
            retry_context = {
                "retry_count": retry_count,

                "evaluation_feedback":
                    state.get(
                        "evaluation_feedback"
                    ),

                "rca_quality_check":
                    state.get(
                        "rca_quality_check"
                    ),

                "incident_context":
                    state.get(
                        "incident_context"
                    ),
            }

            # Определяем финальный запрос с учетом предыдущих раундов исследований для процесса replanning
            supervisor_messages.append(
                SystemMessage(
                    content=(
                        "This is an additional "
                        "investigation round.\n\n"
                        "Previous investigation state:\n"
                        f"{json.dumps(
                            retry_context,
                            ensure_ascii=False,
                            indent=2,
                            default=str,
                        )}\n\n"
                        "Select specialists required "
                        "to obtain the missing evidence. "
                        "Do not automatically repeat all "
                        "previous specialists."
                    )
                )
            )

        # Planning или Replaning
        # Получаем объект класс SupervisorDecision с required_agents и supervisor_reason
        decision: SupervisorDecision = await supervisor_model.ainvoke(
            supervisor_messages, 
            config=config
        )

        print(
            "SUPERVISOR ROUND:",
            state.get(
                "evaluation_retry_count",
                0,
            )
        )

        print(
            "EVALUATION FEEDBACK:",
            state.get(
                "evaluation_feedback"
            )
        )

        return {
            "required_agents": decision.required_agents,
            "supervisor_reason": decision.reason,
            "supervisor_error": None,
        }
    except Exception as exc:
        return {
            "required_agents": [],
             "supervisor_reason": (
                "Supervisor planning failed because the model output "
                "did not match the SupervisorDecision schema."
             ),
              "supervisor_error": {
                "type": "supervisor_structured_output_error",
                "message": str(exc),
              }
        }


###################################################
## Node supervisor_error_node
###################################################
def supervisor_error_node(
    state: SREAgentState,
):
    """
    Return a controlled response when supervisor planning fails.
    """

    error = state.get("supervisor_error") or { 
        "type": "unknown_supervisor_error",
        "message": "Supervisor decision is missing.",
    }

    return {
        "messages": AIMessage(
            content=(
                "Не удалось определить набор специалистов, "
                "необходимых для выполнения запроса.\n\n"
                f"Причина: {error.get('message')}" 
            )
        )
    }



###################################################
## Node evaluator_node
###################################################

async def evaluator_node(
    state: SREAgentState,
    config: RunnableConfig,
    store: BaseStore,
):
    """
    Evaluate whether aggregated IncidentContext
    is sufficient for RCA / final synthesis.

    Responsibilities:
    - consume only normalized IncidentContext;
    - evaluate evidence quality;
    - produce RCAQualityCheck;
    - decide whether another collection round may be required.

    Must NOT:
    - call Kubernetes tools;
    - search runbooks;
    - modify long-term memory;
    - generate the RCA;
    - answer the user.
    """

    incident_context = state.get(
        "incident_context"
    )

    if not incident_context:
        return {
            "rca_quality_check": {
                "has_evidence": False,
                "has_clear_root_cause": False,
                "has_next_actions": False,
                "needs_more_data": True,
            },
            "evaluator_error": {
                "type": "missing_incident_context",
                "message": (
                    "evaluator_node requires "
                    "state.incident_context."
                ),
            },
            "evaluation_feedback": (
                "IncidentContext is missing. "
                "Another data collection round is required."
            ),
        }

    system_prompt = (
        RCA_EVALUATOR_SYSTEM_PROMPT.format(
            incident_context=json.dumps(
                incident_context,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    )

    try:
        quality_check: RCAQualityCheck = await evaluator_model.ainvoke(
            [
                SystemMessage(
                    content=system_prompt
                )
            ],
            config=config,
        )


        return {
            "rca_quality_check":
                quality_check.model_dump(
                    mode="json"
                ),
            "evaluation_feedback": (
                quality_check.evaluation_summary
                if quality_check.needs_more_data
                else None
            ),
            "evaluator_error": None,
        }

    except Exception as exc:
        return {
            "rca_quality_check": {
                "has_evidence": False,
                "has_clear_root_cause": False,
                "has_next_actions": False,
                "needs_more_data": True,
            },
            "evaluator_error": {
                "type":
                    "evaluator_structured_output_error",
                "message": str(exc),
            },
            "evaluation_feedback": (
                "Evaluation failed; collected evidence "
                "cannot yet be trusted for RCA synthesis."
            ),
        }



###################################################
## Condition Edge  dispatch_specialists
###################################################

def dispatch_specialists(state: SREAgentState):
    """
    Dynamic parallel fan-out after supervisor.

    Supervisor has already determined required_agents.
    This function converts that execution plan into Send objects.

    Multiple Send objects returned from the same conditional edge
    are executed in parallel by LangGraph.
    """

    if state["supervisor_error"]:
        return "supervisor_error"

    # получаем тип данных SupervisorAgentName
    required_agents = state.get("required_agents", [])

    # Контейнер для объектов Send
    sends = []

    agent_to_node = {
        "kubernetes": "kubernetes_agent_subgraph",
        "memory": "memory_agent_subgraph",
        "runbook": "runbook_agent_node",
        "chat": "chat_agent_node",
    }

    for agent_name in required_agents:

        node_name = agent_to_node.get(agent_name)

        if node_name is None:
            raise ValueError(
                f"No graph node registered for specialist: {agent_name}"
            )
            
        sends.append(
            Send(node_name, state)              # Инициализируцем объект Send
        )

    # Если sends list без специалистов подними исключение
    if not sends:
        raise ValueError(
            "Supervisor selected no executable specialists."
        )

    # LangGragh получает список Send и инициирует parallel workers
    return sends


###################################################
## Condition Edge  route_after_evaluator
###################################################
def route_after_evaluator (state: SREAgentState
) -> Literal[
    "need_more_data",
    "final_response",
]:
    """
    Decide whether the investigation is complete
    or another supervisor-controlled collection
    round is required.
    """

    MAX_EVALUATION_RETRIES = 2

    # Читаем dict as RCAQualityCheck
    quality = state.get("rca_quality_check")

    # Читаем количество возможных итераций
    retry_count = state.get("evaluation_retry_count", 0)

    # Раунд 1  (исследование вызывает специалистов)
    # RCAQualityCheck не существует и количетсво циклов сбора доказательств меньше MAX_EVALUATION_RETRIES
    if not quality:
        if retry_count < MAX_EVALUATION_RETRIES:
            # запускаем еще один раунд исследования
            return "need_more_data"

        # Termination condition
        return "final_response"

    # Раунд 2 (исследование продолжается и вызывает специалистов)
    # Читаем RCAQualityCheck.needs_more_data значение тип данных bool
    needs_more_data = quality.get("needs_more_data", True)

    # Проверяем на условие Termination condition
    if (needs_more_data and retry_count < MAX_EVALUATION_RETRIES):
        return "need_more_data"

    # Если needs_more_data False раунды исследования завершаются
    return "final_response"





###################################################
## Condition Edge route_after_human_approval
################################################### 
def route_after_human_approval(state: SREAgentState) -> Literal[
    "approved",
    "rejected",
]:
    status = state.get("approval_status")

    if status == "approved":
        return "approved"

    return "rejected"



##################################################
## Node approval_rejected_node
###################################################
def approval_rejected_node(
    state: SREAgentState,
):
    """
    Finish RCA workflow when human rejects
    final RCA generation.
    """

    message = (
        "Incident report publication was rejected "
        "by the human reviewer."
    )

    feedback = state.get("approval_feedback")

    if feedback:
        message = message + (
            "\n\nReviewer feedback:\n"
            f"{feedback}"
        )

    return {
        "messages": [
            AIMessage(
                content=message
            )
        ]
    }





###################################################
## Node aggregate_findings_node
###################################################

def aggregate_findings_node(
    state: SREAgentState,
):
    """
    Week 5 Day 4.

    Fan-in / aggregation node.

    Responsibilities:
    - collect specialist outputs;
    - normalize them into IncidentContext;
    - preserve evidence without inventing information;
    - expose one contract for agents.

    Must NOT:
    - call an LLM;
    - call tools;
    - perform Kubernetes diagnostics;
    - search runbooks;
    - update long-term memory;
    - generate RCA;
    - answer the user.
    """

    try:
        # --------------------------------
        # Kubernetes specialist output
        # --------------------------------

        kubernetes_evidence = state.get(
            "diagnostic_answer"
        )

        # --------------------------------
        # Runbook specialist output
        # --------------------------------

        runbook_evidence = state.get(
            "relevant_runbook"
        )

        # --------------------------------
        # Long-term memory evidence
        # --------------------------------

        memory_evidence = state.get(
            "relevant_memory_context"
        )

        # --------------------------------
        # Collect specialist errors
        # --------------------------------

        errors = {}

        if state.get("runbook_error"):
            errors["runbook"] = state[
                "runbook_error"
            ]

        if state.get("memory_read_error"):
            errors["memory"] = state[
                "memory_read_error"
            ]

        if state.get("k8s_guardrail_violation"):
            errors["kubernetes"] = state[
                "k8s_guardrail_violation"
            ]

        # --------------------------------
        # Build normalized contract
        # --------------------------------

        incident_context = IncidentContext(
            kubernetes_evidence=kubernetes_evidence,
            runbook_evidence=runbook_evidence,
            memory_evidence=memory_evidence,
            completed_agents=list(
                dict.fromkeys(
                    state.get(
                        "completed_agents",
                        [],
                    )
                )
            ),
            errors=errors,
        )



        return {
            "incident_context": incident_context.model_dump(mode="json"),
            "aggregation_error": None,
        }

    except Exception as exc:
        return {
            "incident_context": None,
            "aggregation_error": {
                "type": "incident_context_aggregation_error",
                "message": str(exc),
            },            
        }



###################################################
## Node prepare_retry_node
###################################################

def prepare_retry_node(
    state: SREAgentState,
):
    """
    Prepare another evidence-collection round.

    Responsibilities:
    - increment retry counter;
    - invalidate previous supervisor execution plan;
    - preserve evaluator feedback for replanning.
    """

    current_retry_count = state.get(
        "evaluation_retry_count",
        0,
    )

    return {
        "evaluation_retry_count":
            current_retry_count + 1,

        # Старый execution plan больше не считается актуальным.
        "required_agents": [],
        "supervisor_reason": None,
        "supervisor_error": None,
    }


###################################################
## Node final_rca_node
###################################################
async def final_rca_node(
    state: SREAgentState,
    config: RunnableConfig,
    store: BaseStore,
):
    """
    Final RCA synthesis.

    Responsibilities:
    - consume IncidentContext;
    - consume RCAQualityCheck;
    - create final structured RCA;
    - render final user-facing response.

    Must NOT:
    - call Kubernetes tools;
    - call specialists;
    - perform another investigation;
    - modify memory;
    - invent evidence.
    """

    # Читаем сгенерированный из state.
    incident_context = state.get("incident_context")

    # Читаем сгенерированный из state
    rca_quality_check = state.get("rca_quality_check")

    if not incident_context:
        return {
                    "messages": [
                        AIMessage(
                            content=(
                                "RCA cannot be generated because "
                                "IncidentContext is missing."
                            )
                        )
                    ]
                }


    system_prompt = (
        FINAL_RCA_SYSTEM_PROMPT.format(
            incident_context=json.dumps(
                incident_context,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            quality_check=json.dumps(
                rca_quality_check,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )
    )

    try:
        rca: FinalRCA = await final_rca_model.ainvoke(
            [
                SystemMessage(
                    content=system_prompt
                ),
                *state["messages"],
            ],
            config=config
        )


        return {
            "incident_report": rca.model_dump(mode="json"),
            "incident_report_error": None,
            "active_agent": "final_rca_node",
            }

    except Exception as exc:
        return {
                    "incident_report": None,
                    "incident_report_error": {
                        "type": "final_rca_structured_output_error",
                        "message":
                            str(exc),
                    }
                }



###################################################
## Node publish_incident_report_node
###################################################
def publish_incident_report_node(state: SREAgentState):
    """
    Human-in-the-loop gate before incident report publication.

    Responsibilities:
    - read the generated RCA draft;
    - expose the draft to the human reviewer;
    - pause graph execution using interrupt();
    - receive approval / rejection after resume;
    - publish RCA only after approval.

    Must NOT:
    - generate a new RCA;
    - call LLM;
    - call Kubernetes tools;
    - modify evidence;
    - modify long-term memory.
    """

    # Читаем сгенерированный draft incident_report из state.
    incident_report = state.get("incident_report")

    if not incident_report:
        return {
            "incident_report_error": {
                "type": "missing_incident_report",
                "message": (
                    "Cannot publish incident report "
                    "because RCA draft is missing."
                ),
            }
        }

    # Approval can be disabled if approval_required = False
    if not state.get("approval_required", False):
        # Создаем объект класса FinalRCA, путем вызова classmethod .model_validate() который верифицирует соотвествие входнго dict схеме класса.
        rca = FinalRCA.model_validate(incident_report)

        return {
                "approval_status": "approved",
                "approval_feedback": None,
                "messages": [
                    AIMessage(
                        content=render_final_rca(rca)
                    )
                ],
            }

    # --------------------------------
    # Dynamic interrupt
    # --------------------------------

    ''' 
    LangGraph останавливает execution при interrupt() и human_response еще не получает значения.
    После resume LangGraph повторно запускает interrupted node с начала. 
    Документация LangGraph отдельно подчёркивает: при resume выполнение interrupted node начинается заново, 
    поэтому код до interrupt() тоже выполняется повторно.


    Затем извне ты вызываешь:
    Command(
        resume={
            "approved": True,
            "feedback": None,
        }
    )

    И при resume:
    
    human_response =  {"approved": True, "feedback": None}

    Значение из Command(resume=...) становится результатом interrupt()

    После resume LangGraph повторно запускает interrupted node с начала. 
    Документация LangGraph отдельно подчёркивает: при resume выполнение interrupted node начинается заново, 
    поэтому код до interrupt() тоже выполняется повторно.
    '''
    human_response = interrupt(
        {
            "type": "incident_report_review",
            "message": (
                "Review the draft RCA before publication."
            ),
            "draft_rca": incident_report,
        }
    )

    # --------------------------------
    # Validate resume value
    # --------------------------------

    # Проверяем тип данных human_response
    if not isinstance(human_response, dict):
        raise ValueError(
            "Incident report review response "
            "must be a dictionary."
        )

    # Читаем значения 
    approved = human_response.get("approved", False)
    feedback = human_response.get("feedback", None)
    # --------------------------------
    # Rejected
    # --------------------------------

    if not approved:
        return {
            "approval_status": "rejected",
            "approval_feedback": feedback,
        }

    # --------------------------------
    # Approved -> publish
    # --------------------------------
    rca = FinalRCA.model_validate(incident_report)

    # Create manually AIMessage 
    return {
            "approval_status": "approved",
            "approval_feedback": feedback,
            "messages": [
                AIMessage(
                    content=render_final_rca(rca)
                )
            ],
        }





###################################################
## GRAPH
###################################################
def build_graph():

    supervisor_builder = StateGraph(SREAgentState)

    # -------------------------
    # Nodes
    # -------------------------
    
    supervisor_builder.add_node(
        "supervisor_node",
        supervisor_node,
    )

    supervisor_builder.add_node(
        "kubernetes_agent_subgraph",
        kubernetes_agent_subgraph,
    )

    supervisor_builder.add_node(
        "runbook_agent_node",
        runbook_agent_node,
    )

    supervisor_builder.add_node(
        "memory_agent_subgraph",
        memory_agent_subgraph,
    )

    supervisor_builder.add_node(
        "chat_agent_node",
        chat_agent_node,
    )

    supervisor_builder.add_node(
        "aggregate_findings_node",
        aggregate_findings_node,
    )

    supervisor_builder.add_node(
        "evaluator_node",
        evaluator_node,
    )

    supervisor_builder.add_node(
        "prepare_retry_node",
        prepare_retry_node,
    )

    supervisor_builder.add_node(
        "final_rca_node",
        final_rca_node,
    )

    supervisor_builder.add_node(
        "publish_incident_report_node",
        publish_incident_report_node,
    )


    supervisor_builder.add_node(
        "supervisor_error",
        supervisor_error_node,
    )

    supervisor_builder.add_node(
        "approval_rejected_node",
        approval_rejected_node,
    )


    # -------------------------
    # START
    # -------------------------

    supervisor_builder.add_edge(
        START,
        "supervisor_node",
    )


    # -------------------------
    # Dynamic parallel fan-out (Send)
    # -------------------------

    supervisor_builder.add_conditional_edges(
        "supervisor_node",
        dispatch_specialists,
    )


    # -------------------------
    # Fan-in
    # -------------------------

    supervisor_builder.add_edge(
        "memory_agent_subgraph",
        "aggregate_findings_node",
    )


    supervisor_builder.add_edge(
        "runbook_agent_node",
        "aggregate_findings_node",
    )

    supervisor_builder.add_edge(
        "kubernetes_agent_subgraph",
        "aggregate_findings_node",
    )

    # -------------------------
    # Chat bypasses the RCA / evaluator / approval pipeline entirely.
    # -------------------------

    supervisor_builder.add_edge(
        "chat_agent_node",
        END,
    )

    # -------------------------
    # Aggregation → Evaluation
    # -------------------------
    supervisor_builder.add_edge(
        "aggregate_findings_node",
        "evaluator_node",
    )

    # -------------------------
    # Evaluation decision
    # -------------------------

    supervisor_builder.add_conditional_edges(
        "evaluator_node",
        route_after_evaluator,
        {
            "need_more_data": "prepare_retry_node",
            "final_response": "final_rca_node",
        },
    )

    # -------------------------
    # Agentic feedback loop
    # -------------------------
    supervisor_builder.add_edge(
        "prepare_retry_node",
        "supervisor_node",
    )

    # -------------------------
    # Publish Edge
    # -------------------------
    supervisor_builder.add_edge(
        "final_rca_node",
        "publish_incident_report_node",
    )

    # -------------------------
    #  Approval Routing to Publish incident_report
    # -------------------------
    supervisor_builder.add_conditional_edges(
        "publish_incident_report_node",
        route_after_human_approval,
        {
            "approved": END,
            "rejected": "approval_rejected_node",
        },
    )


    # -------------------------
    # Final
    # -------------------------
    supervisor_builder.add_edge(
        "approval_rejected_node",
        END,
    )

    supervisor_builder.add_edge(
        "supervisor_error",
        END,
    )

    # -------------------------
    #  Graph
    # -------------------------

    # LangGraph сохраняет checkpoints на boundaries graph execution; persistence используется в том числе для resume после interrupt и recovery.
    return  supervisor_builder.compile()

# Вызываемый Объект указанный в langgraph.json
graph = build_graph()
