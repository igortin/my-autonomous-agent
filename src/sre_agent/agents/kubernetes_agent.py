from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from kubernetes import config as kube_config

from langgraph.graph import StateGraph, MessagesState, END, START
from typing import TypedDict, Literal, Optional, Any, Annotated
import operator
from langchain_core.runnables import RunnableConfig
# Across THREAD Memory
from langgraph.store.base import BaseStore

import sys, json, yaml, re
from sre_agent.state import (
    SREAgentState,
    DiagnosticAnswer,
    MemoryAgentState,
    keep_latest_value,
)
from sre_agent.tools.kubernetes import (
    KUBERNETES_TOOLS,
    default_kubernetes_clusters_config_path,
    load_kubernetes_clusters,
)
from sre_agent.model import model
from sre_agent.memory import relevant_memory_read_node


#####################################################
## KUBERNETES AGENT STATE
#####################################################

# total=False: чтобы не требовать все поля при вызове графа
class KubernetesAgentState(MessagesState, total=False):
    """
    State contract for the reusable kubernetes subgraph.
    """
    # Специальное поле Guardrail
    k8s_guardrail_violation: dict[str, Any] | None

    # Structured Kubernetes diagnostic result
    diagnostic_answer: dict[str, Any] | None

    # Входной контекст для Kubernetes specialist
    kubernetes_request: str | None

    # Результат диагностики
    k8s_result: dict[str, Any] | None

    # Если у тебя используется ReAct/tool calling
    k8s_action: str | None

    # Ошибка specialist-а
    kubernetes_error: str | None

    # Только память, релевантная текущему запросу
    relevant_memory_context: Annotated[dict[str, Any], operator.or_]

    # Optional reason why another collection round is needed
    evaluation_feedback: str | None

    # Evaluator structured-output/runtime error
    evaluator_error: dict[str, Any] | None

    # Number of data collection retries by evaluator (termination condition)
    evaluation_retry_count: int

    # Normalized evidence collected from specialist agents
    incident_context: dict[str, Any] | None

    # Какой specialist agent обработал запрос
    active_agent: Annotated[str | None, keep_latest_value]

    # Parallel execution Send use Reducer
    completed_agents: Annotated[list[str], operator.add]


#####################################################
## KUBERNETES AGENT SYSTEMPROMPT
#####################################################

KUBERNETES_AGENT_SYSTEM_PROMPT = """
You are a Kubernetes diagnostics specialist operating in STRICT READ-ONLY MODE.

Your responsibilities:

* investigate Kubernetes clusters, namespaces, pods, nodes, logs, events, and resource status;
* use only the Kubernetes tools available to you;
* use relevant saved memory when it helps resolve cluster or namespace context;
* gather concrete evidence before reaching a conclusion;
* never invent tool results;
* never perform destructive or state-changing operations.

Relevant long-term memory:
<relevant_memory_context>
{relevant_memory_context}
</relevant_memory_context>

Investigation feedback:
<evaluation_feedback>
{evaluation_feedback}
</evaluation_feedback>

Previous incident context:
<incident_context>
{incident_context}
</incident_context>

If evaluation_feedback is present:

- treat this as an additional investigation round;
- focus on obtaining the specifically missing evidence;
- do not blindly repeat diagnostics already represented
  in IncidentContext;
- use Kubernetes tools required to close the identified evidence gaps.

Operational rules:

1. Call Kubernetes tools whenever current cluster state is required.
2. Prefer concrete tool results over assumptions.
3. After receiving tool results, determine whether additional evidence is required.
4. Continue calling tools only while additional evidence is necessary.
5. Stop calling tools when sufficient evidence has been collected.
6. Do not generate the final user-facing DiagnosticAnswer structure.
   A separate formatter node will create the final DiagnosticAnswer.

Cluster resolution rules:

1. Use the exact cluster name explicitly provided by the user.
2. Do not substitute another cluster from memory.
3. Do not use partial or fuzzy cluster-name matches.
4. If the requested cluster cannot be identified unambiguously, do not invent a cluster name.
5. When a Kubernetes tool requires a cluster identifier, pass the exact resolved cluster name.

Namespace resolution rules:

1. If the user explicitly provides a namespace, use that namespace.
2. Otherwise, identify the Kubernetes cluster explicitly referenced by the user.
3. Search relevant_memory_context for an exact ClusterContext match by cluster name.
4. If an exact matching ClusterContext exists and contains a non-empty default_namespace,
   you MUST explicitly pass that default_namespace to every namespaced Kubernetes tool.
5. If an exact matching ClusterContext exists but default_namespace is missing, null, or empty,
   you MUST explicitly pass "default" to every namespaced Kubernetes tool.
6. If no exact matching ClusterContext exists, use "default" unless the user has explicitly
   provided another namespace.
7. Never rely on a namespaced tool's schema default when the namespace can be resolved
   from the user request or relevant_memory_context.
8. Never use a namespace stored for a different cluster.
9. Never infer a namespace from a partial, approximate, or similar cluster-name match.
10. Always pass the resolved namespace explicitly to namespaced Kubernetes tools.

Evidence rules:

1. Base all conclusions on tool results and relevant saved memory.
2. Treat saved memory as contextual information, not as proof of current Kubernetes state.
3. Use tools to verify any information that may have changed.
4. Clearly preserve errors, missing resources, permission failures, and unavailable data
   in the evidence collected for the formatter node.
   """

#####################################################
## KUBERNETES MODEL
#####################################################

# Создаем модель для кубернетис запросов и даем знать моделе о наличии инструментов LangChain tool objects (LangChain передает метаданные Tools под капотом) 
kubernetes_model_with_tools = model.bind_tools(
    KUBERNETES_TOOLS, 
    parallel_tool_calls=False,          # Отключаем паралелльный вызов tools
)

# Создаем объект c входным параметром список LangChain Tool objects
kubernetes_tools_node = ToolNode(KUBERNETES_TOOLS)


#####################################################
## KUBERNETES HELPERS
#####################################################

# Конвертация list в str
def render_list(items: list[str]) -> str:
    if not items:
        return "- Нет данных."
    # Конкатинация элементов массва в string
    return "\n".join(f"- {item}" for item in items)


def render_diagnostic_answer(answer: DiagnosticAnswer):
    """
    Convert DiagnosticAnswer object into stable user-facing string as Markdown.
    """
    return (
        "## Summary\n"
        f"{answer.summary}\n\n"
        "## Evidence\n"
        f"{render_list(answer.evidence)}\n\n"
        "## Likely causes\n"
        f"{render_list(answer.likely_causes)}\n\n"
        "## Recommended commands\n"
        f"{render_list(answer.recommended_commands)}\n\n"
        "## Next actions\n"
        f"{render_list(answer.next_actions)}\n\n"
        "## Memory context used\n"
        f"{render_list(answer.memory_sources)}"
    )

#####################################################
## KUBERNETES GUARDRAILS HELPERS
#####################################################

def detect_destructive_k8s_request(text: str) -> Optional[dict[str: Any]]:
    """
    Detect obviously destructive Kubernetes requests.  
    """

    # Переводим в нижний регистр текст чтобы быть не чувствительным к регистру
    normalized = text.lower()

    for pattern in DESTRUCTIVE_K8S_PATTERNS:
        # поиск на вхождение pattern в строке normalized
        if re.search(pattern, normalized):
            return{
                "type": "destructive_k8s_action_forbidden",
                "message": "Destructive Kubernetes actions are forbidden in read-only mode.",
                "matched_pattern": pattern,
                "request": text
            }

    return None


#####################################################
## KUBERNETES GUARDRAILS
#####################################################

"""
Паттерн соотвествует
- Правило 1: kubectl exec и т.п.
- Правило 2: scale service и т.п.
- Правило 3: создай namespace и т.п.
"""

DESTRUCTIVE_K8S_PATTERNS = [
    r"\bkubectl\s+(delete|apply|create|edit|patch|replace|scale|drain|cordon|uncordon|taint|label|annotate|exec|cp|port-forward)\b",
    r"\b(delete|remove|kill|restart|scale|patch|apply|create|edit|replace|drain|cordon|uncordon)\b.*\b(pod|pods|node|nodes|deployment|deploy|service|svc|namespace|ns|secret|configmap|pvc|ingress)\b",
    r"\b(удали|удалить|снеси|убей|перезапусти|рестартни|масштабируй|заскейль|примени|создай|измени|запатчи)\b.*\b(pod|под|поду|pods|нода|node|deployment|deploy|service|namespace|ns|ingress|pvc)\b",
]


def get_latest_human_text(state: SREAgentState) -> str:
    """
    Return latest HumanMessage content from graph state.
    """

    for message in reversed(state["messages"]):
        # Получаем тока HumanMessage
        if isinstance(message, HumanMessage):
            # Возращаем текст пользовательсмкого вопроса 
            return message.content if isinstance(message.content, str) else str(message.content)



def tool_guardrail_node(
    state: KubernetesAgentState,
    config: RunnableConfig,
    store: BaseStore,
):
    """
    Node: tool_guardrail_node

    Responsibility:
    - Check latest user request before run Kubernetes ReAct loop.
    - Block Destructive Kubernetes actions.
    - Do not call LLM.
    - Do not call tools.
    """
    
    # Получаем последний запрос пользователя из state 
    user_text = get_latest_human_text(state)

    # Проверяем пользовательский запрос на запрещенные просьбы 
    violation = detect_destructive_k8s_request(user_text)

    # LangGraph перехватит dict и перезапишет значение в атрибут SREAgentState.k8s_guardrail_violation
    return {
        "k8s_guardrail_violation": violation
    }


def k8s_readonly_refusal_node(state: KubernetesAgentState, config: RunnableConfig, store: BaseStore):
    """
    Node: k8s_readonly_refusal_node

    Responsobilities:
    - Return safe refusal for distructive Kubernetes request.
    - Preserve the same DiagnosticAnswer final format.

    ```
    violation = {
        "type": "destructive_k8s_action_forbidden",
        "message": "Destructive Kubernetes actions are forbidden in read-only mode.",
        "matched_pattern": pattern,
        "request": text
    }
    ```
    """

    violation = state.get("k8s_guardrail_violation") or {}

    answer = DiagnosticAnswer(
        summary=(
            "Запрос относится к destructive Kubernetes action, поэтому действие не может быть выполнено "
            "в read-only режиме."
        ),
        evidence=[
            "Kubernetes assistant работает в STRICT READ-ONLY MODE.",
            f"Blocked request: {violation.get('request')}",
            f"Matched guardrail pattern: {violation.get('matched_pattern')}",
        ],
        likely_causes=[
            "Пользователь запросил операцию, которая может изменить состояние Kubernetes cluster.",
            "Запрос относится к delete/restart/scale/apply/patch/create/exec/drain/cordon или похожей операции.",
        ],
        recommended_commands=[
            "kubectl get pods -A",
            "kubectl get events -A --sort-by=.lastTimestamp",
            "kubectl get nodes -o wide",
        ],
        next_actions=[
            "Выполнить только read-only диагностику перед любыми изменениями.",
            "Проверить pod details, pod events, logs, node status или node events.",
            "Для destructive action использовать отдельный workflow с human approval.",
        ],
    )

    return {
        "diagnostic_answer": answer.model_dump(mode="json"),
        "messages": [
            AIMessage(content=render_diagnostic_answer(answer))
        ],
    }


#####################################################
##  Node kubernetes_agent_node
#####################################################
# MCP tools используют асинхронное выполнение
async def kubernetes_agent_node(
    state: KubernetesAgentState,
    config: RunnableConfig,
    store: BaseStore,
):
    """
    Kubernetes ReAct specialist using relevant long-term memory.

    Node: kubernetes_agent_node

     Responsibilities:
    - analyze the Kubernetes request;
    - use relevant long-term memory;
    - decide whether a Kubernetes tool is required;
    - create Kubernetes tool calls;
    - analyze ToolMessage results;
    - do not perform request routing;
    - do not use MCP tools;
    - do not produce the final structured diagnostic format.

    Модель создает вызов инструмента
    ```
    AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_pod_logs",
                "args": {
                    ...
                },
                "id": "call_123",
                "type": "tool_call",
            }
        ],
    )
    ```
    """

    # Рендерим Tool System Prompt
    system_prompt = KUBERNETES_AGENT_SYSTEM_PROMPT.format(
        relevant_memory_context=json.dumps(
            state.get("relevant_memory_context"),
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        evaluation_feedback=json.dumps(
            state.get("evaluation_feedback"),
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        incident_context=json.dumps(
            state.get("incident_context"),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    #  Вызываем LLM для генерации AIMessage, передаем System Prompt и всю историю сообщений пользоавтельского запроса.
    response = await kubernetes_model_with_tools.ainvoke(
        [SystemMessage(content=system_prompt)] + state["messages"]
    )

    # LangGraph добавляет AIMessage без и с tool_calls в state.messages
    return {
        "messages": [response],
    }


#####################################################
##  Conditional Edge GUARDRAILS
#####################################################

def route_after_k8s_guardrail(
    state: SREAgentState,
) -> Literal["k8s_readonly_refusal_node", "kubernetes_agent_node"]:
    """
    Conditional Edge.

    Route destructive requests to refusal and safe requests
    to the Kubernetes ReAct specialist.
    """

    # Проверка атрибута state.k8s_guardrail_violation что не None
    if state.get("k8s_guardrail_violation"):
        return "k8s_readonly_refusal_node"

    return "kubernetes_agent_node"


def validate_kubernetes_cluster_registry() -> None:
    """
    Helper функция проверяет, что все 'context' указанные в KUBERNETES_CLUSTERS (dict) существуют в ~/.kube/config (kubeconfig)

    To list contexts in ~/.kube/config
    kubectl config get-contexts -o name

    This validation runs before the ReAct Agent starts.
    """
    KUBERNETES_CLUSTERS = load_kubernetes_clusters(default_kubernetes_clusters_config_path())

    # Создаем список ошибок для запонения при не найденном context в ~/.kube/config
    validation_errors: list[str] = []

    # Итерируемся по cluster registry
    for alias, cluster_config in KUBERNETES_CLUSTERS.items():
        try:
            # Читаем список contexts из фйала ~/.kube/config если kubeconfig_file установлен None
            list_contexts, _ = (kube_config.list_kube_config_contexts(
                  config_file=(
                        cluster_config.kubeconfig_file                    #  указываем путь к kubeconfig и читаем в нем все context-ы
                    ),
                )    
            )

            # Создаем список имен context-ов определенных в фйале ~/.kube/config
            available_context_name = [context["name"] for context in list_contexts]

            # Поиск конфигурации из KUBERNETES_CLUSTERS в available_context_name
            if cluster_config.context not in available_context_name:
                raise validation_errors.append(
                    f"Cluster alias {alias!r}: "                            # !r указываем установить '' 
                    f"context "
                    f"{cluster_config.context!r} "
                    f"was not found in file kubeconfig. "
                    f"Available contexts: "
                    f"{sorted(available_context_name)}"
                )


        except Exception as exc:
            validation_errors.append(
                f"Cluster alias {alias}: "
                f"failed to load kubeconfig: "
                f"{type(exc).__name__}: {exc}"
            )

    if validation_errors:
        raise RuntimeError("Invalid Kubernetes cluster registry:\n- " + "\n- ".join(validation_errors))

    return None



#####################################################
##  Node format_k8s_diagnostic_answer_node SYSTEM PROMPT
#####################################################
KUBERNETES_DIAGNOSTIC_FINAL_PROMPT="""You are a final response formatter for a Kubernetes SRE assistant.

Your job:
- Produce the final Kubernetes diagnostic answer.
- Always return data that matches the DiagnosticAnswer schema.
- Use only information from the conversation and Kubernetes tool results.
- Do not invent pod names, node names, events, logs, namespaces, errors, or metrics.
- If evidence is insufficient, explicitly say that evidence is insufficient.

Safety rules:
- The assistant operates in STRICT READ-ONLY MODE.
- recommended_commands must contain only read-only kubectl commands.
- Never recommend destructive commands such as:
  kubectl delete, apply, create, edit, patch, replace, scale, drain, cordon, uncordon, taint, label, annotate, exec, cp, or port-forward.
- Prefer commands such as:
  kubectl get pods
  kubectl describe pod
  kubectl logs
  kubectl get events
  kubectl get nodes
  kubectl describe node

Field rules:
- summary: one short paragraph.
- evidence: concrete observations from tool outputs or conversation.
- likely_causes: possible causes based on evidence, not guesses.
- recommended_commands: safe read-only kubectl commands only.
- next_actions: practical next steps for the SRE/operator.
- memory_sources: long-term memory facts actually used during parameter resolution.

Memory provenance rules:
- Inspect the latest user request, tool calls and relevant_memory_context.
- Use this format:
  "Used saved name '<cluster_name>': default_namespace='<namespace>'."
- Never claim that memory was used unless the value exists in
  relevant_memory_context.
- Never use a namespace from a different cluster.
- If the user explicitly provided namespace, do not claim that namespace
  was selected from memory.
- If the user omitted namespace and a Kubernetes tool was called with default_namespace from an exact matching ClusterContext, add an explicit memory_sources entry.
- If no long-term memory was used, return an empty memory_sources list.

Relevant long-term memory:
<relevant_memory_context>
{relevant_memory_context}
</relevant_memory_context>
"""

#####################################################
##  MODEL diagnostic_answer_model 
#####################################################

# Создаем модель для превращения AIMessage от ноды kubernetes_agent_node в  структуированный обьект DiagnosticAnswer (фиксированная схема)
diagnostic_answer_model = model.with_structured_output(
    DiagnosticAnswer,
)

#####################################################
##  Node format_k8s_diagnostic_answer_node
#####################################################

async def format_k8s_diagnostic_answer_node(state: KubernetesAgentState, config: RunnableConfig, store: BaseStore):
    """
    Node: format_k8s_diagnostic_answer_node

    Responsibility:
    - Read full Kubernetes ReACt conversation history.
    - Read ToolMessage results already added by ToolNode.
    - Ask LLM to produce DiagnsticAnswer structured object.
    - Render stable Markdown sections for the user.
    - Store structured diagnostic answer in graph state.
    """
    relevant_memory_context = state.get(
        "relevant_memory_context",
        {},
    )

    system_msg = KUBERNETES_DIAGNOSTIC_FINAL_PROMPT.format(
        relevant_memory_context=json.dumps(
            relevant_memory_context,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    try:
        # вызов LLM с with_structured_output и она создает объект класс DiagnosticAnswer
        answer: DiagnosticAnswer = await diagnostic_answer_model.ainvoke(
            [
                SystemMessage(content=system_msg), 
                *state["messages"]
            ]
        )

        # Возращаем с answer JSON-safe Python dict
        return {
            "diagnostic_answer": answer.model_dump(mode="json"),                                        # Сохраняем dict представление объекта "answer" класса DiagnosticAnswer в атрибут state.diagnostic_answer                                        
            "messages": [   
                AIMessage(content=render_diagnostic_answer(answer))                                     # Сохраняем AIMessage с string представление объекта "answer" класса DiagnosticAnswer 
            ],
            "active_agent": "kubernetes_agent_subgraph",
            "completed_agents": ["kubernetes"]
        }

    # Если не получилось у LLM создать объект "answer" класса DiagnosticAnswer
    except Exception as exc:

        # Создаем объект класса DiagnsticAnswer
        fallback_answer = DiagnosticAnswer(
            summary="Не удалось сформировать структурированный Kubernetes diagnostic answer.",
            evidence=[
                "Structured output validation failed.",
                f"Error: {str(exc)}",
            ],
            likely_causes=[
                "Модель вернула ответ, который не соответствует DiagnosticAnswer schema.",
                "В prompt или входных данных может быть недостаточно контекста.",
            ],
            recommended_commands=[
                "kubectl get pods -A",
                "kubectl get events -A --sort-by=.lastTimestamp",
            ],
            next_actions=[
                "Проверить ошибку structured output validation.",
                "Уточнить system prompt для финального formatter node.",
                "Повторить запрос с более конкретным cluster_name, namespace, pod_name или node_name.",
            ],
        )

        # Возращаем dict с объектом fallback_answer
        return {
            "diagnostic_answer": fallback_answer.model_dump(mode="json"),            # Сохраняем JSON представление объекта "answer" класса DiagnosticAnswer в атрибут state.diagnostic_answer
            "messages": [                                                            # Сохраняем AIMessage с string представление объекта "answer" класса DiagnosticAnswer 
                AIMessage(content=render_diagnostic_answer(fallback_answer))
            ],
            "active_agent": "kubernetes_agent_subgraph",
            "completed_agents": ["kubernetes"]
        }


#####################################################
##  Conditional Edge KUBERNETES Инструменты 
#####################################################

def route_after_kubernetes_agent(state: SREAgentState) -> Literal["kubernetes_tools_node", "format_k8s_diagnostic_answer_node"]:
   """
   Condiftion Edge

   Decide whether the Kubernetes ReAct loop should execute tools
   or continue to the final structured diagnostic formatter.
   """

   last_message = state["messages"][-1]

   tool_calls = getattr(last_message, "tool_calls", None)

   if tool_calls:
      return "kubernetes_tools_node"

   return "format_k8s_diagnostic_answer_node"


#####################################################
## Построение kubernetes_agent_subgraph.
#####################################################

def kubernetes_agent_subgraph():

    # Создание Subgraph c explicit state schema
    kubernetes_subgraph_builder = StateGraph(KubernetesAgentState)

    kubernetes_subgraph_builder.add_node("relevant_memory_read_node", relevant_memory_read_node)

    # Kubernetes branch
    kubernetes_subgraph_builder.add_node("tool_guardrail_node", tool_guardrail_node)

    kubernetes_subgraph_builder.add_node("k8s_readonly_refusal_node", k8s_readonly_refusal_node)

    kubernetes_subgraph_builder.add_node("kubernetes_agent_node", kubernetes_agent_node)

    kubernetes_subgraph_builder.add_node("kubernetes_tools_node", kubernetes_tools_node)

    # Output branch
    kubernetes_subgraph_builder.add_node("format_k8s_diagnostic_answer_node", format_k8s_diagnostic_answer_node)

    # START
    kubernetes_subgraph_builder.add_edge(START,"relevant_memory_read_node",)

    kubernetes_subgraph_builder.add_edge("relevant_memory_read_node", "tool_guardrail_node")

    # Guardrail routing
    kubernetes_subgraph_builder.add_conditional_edges(
        "tool_guardrail_node",
        route_after_k8s_guardrail,
        {
            "k8s_readonly_refusal_node": "k8s_readonly_refusal_node",
            "kubernetes_agent_node": "kubernetes_agent_node",
        },
    )

    # Read-only refusal
    kubernetes_subgraph_builder.add_edge("k8s_readonly_refusal_node", END)

    # ReAct loop
    kubernetes_subgraph_builder.add_conditional_edges(
        "kubernetes_agent_node",
        route_after_kubernetes_agent,
        {
            "kubernetes_tools_node": "kubernetes_tools_node",
            "format_k8s_diagnostic_answer_node": "format_k8s_diagnostic_answer_node"
        },
    )

    # Return ToolMessage to model
    kubernetes_subgraph_builder.add_edge("kubernetes_tools_node", "kubernetes_agent_node")

    # Save facts memories branch
    kubernetes_subgraph_builder.add_edge("format_k8s_diagnostic_answer_node", END)

    return kubernetes_subgraph_builder.compile()

kubernetes_agent_subgraph = kubernetes_agent_subgraph()