from typing import Literal, Any, Annotated
from pydantic import BaseModel, Field, ConfigDict, field_validator
from langgraph.graph import MessagesState

import operator

# Контракт состояния
SupervisorAgentName = Literal[
    "kubernetes",
    "memory",
    "runbook",
    "chat",
]

# Контракт состояния
class SupervisorDecision(BaseModel):
    """
    План обработки сложного пользовательского запроса.

    Supervisor выбирает всех специалистов, необходимых для полного выполнения запроса.

    it does not:
    - answer the user;
    - call tools;
    - execute specialist agents;
    - update memory;
    - generate an incident report.
    """
    model_config = ConfigDict(extra="forbid")

    required_agents: list[SupervisorAgentName] = Field(
        min_length = 1,
        description = (
            "Unique specialist agents required to fully process "
            "the latest user request."
        )
    )

    reason: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "A explanation of why the selected specialists "
            "are required. Do not provide hidden chain-of-thought."
        )
    )

    # Проверка поля на момент созданием объекта
    @field_validator("required_agents")
    @classmethod
    def normalize_required_agents(cls, value: list[SupervisorAgentName]) -> list[SupervisorAgentName]:
        """
        Remove duplicate agent names while preserving their order.
        """
        # Создаем список уникальных значений сохранив порядок
        unique_agents = list(dict.fromkeys(value))

        if not unique_agents:
            raise ValueError(
                 "At least one specialist agent must be selected."
            )
        
        return unique_agents

    
    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        """
        Reject empty or whitespace-only explanations.
        """
        normalized_reason = value.strip()

        if not normalized_reason:
            raise ValueError("Route reason must not be empty.")

        return normalized_reason


# Контракт состояния
class RCAQualityCheck(BaseModel):
    """
    Structured evaluation of collected incident evidence.

    Evaluator decides whether the current IncidentContext
    is sufficient for reliable RCA / synthesis.
    """

    model_config = ConfigDict(extra="forbid")

    # фактические наблюдения
    has_evidence: bool

    # Можно ли из собранных данных сделать достаточно уверенный вывод:
    has_clear_root_cause: bool

    # Есть ли понятные следующие шаги
    has_next_actions: bool

    # Текущего IncidentContext достаточно или нет для качественного RCA
    needs_more_data: bool

    # полезное улучшение именно для control loop
    missing_evidence: list[str] = Field(
        default_factory=list
    )

    # полезное улучшение именно для control loop
    evaluation_summary: str

# Контракт состояния
class IncidentContext(BaseModel):
    """
    Normalized context collected from specialist agents.

    specialist-specific state
          ↓
    normalized state

    This object is the contract between:
    - evidence collection specialists;
    - RCA/report agents;
    - final synthesis.
    """ 

    model_config = ConfigDict(extra="forbid")

    kubernetes_evidence: dict[str, Any] | None = None

    runbook_evidence: dict[str, Any] | None = None

    memory_evidence: dict[str, Any] | None = None

    completed_agents: list[str] = Field(
        default_factory=list
    )

    errors: dict[str, Any] = Field(
        default_factory=dict
    )

def keep_latest_value(left: str | None, right: str | None) -> str | None:
    """
    Last-write-wins reducer for informational fields with no read-side
    branching (e.g. active_agent).

    dispatch_specialists can Send to multiple specialist nodes in the
    same superstep, and each one sets its own value. Without a reducer,
    LangGraph raises InvalidUpdateError on the second concurrent write.
    """
    return right if right is not None else left

# Контракт состояния (inheret Pydantic)
class AgentGoal(BaseModel):
    """
    Structured representation of the desired environment state.

    AgentGoal is separated from the original user message and acts
    as the execution contract for the autonomous agent.
    """

    # лишние или неправильно названные поля нельзя использовать при инициализации объекта. Поскольку лишние поля не является частью контракта цели.
    model_config = ConfigDict(extra="forbid")

    # нормализованное описание желаемого результата
    description: str = Field(
        min_length=1,
        description=(
            "Human-readable description of the desired environment state."
        ),
    )

    # определяет критерии, по которым evaluator поймёт, что работа завершена
    success_criteria: list[str] = Field(
        min_length=1,
        description=(
            "Observable conditions that must be true before the goal can be considered achieved."
        ),
    )

    # безопасности ограничения
    constraints: list[str] = Field(
        default_factory=list,
        description=(
            "Operational boundaries that every planned action must respect."
        ),
    )

    # лимит автономности агента
    max_iterations: int = Field(
        ge=1,
        le=20,
        description=(
            "Maximum number of autonomous control-loop iterations."
        ),
    )


# total=False: чтобы не требовать все поля при вызове графа
class SREAgentState(MessagesState, total=False):

    """
    Explicit state schema for SRE/Kubernetes assistant.
    """

    # Structured desired state, stored separately from user messages.
    # AgentGoal must be validated before being converted to dict.
    goal: dict[str, Any] | None


    # Полная long-term memory пользователя
    memory_context: dict[str, Any]

    # Только память, релевантная текущему запросу
    relevant_memory_context: Annotated[dict[str, Any], operator.or_]

    # Диагностика memory retrieval
    memory_read_error: dict[str, Any] | None

    # Решение memory router
    memory_route: Literal[
        "profile_memory", 
        "project_memory", 
        "cluster_memory", 
        "none"
    ] | None

    # Результат записи
    memory_updated: bool | None
    memory_update_error: dict[str, Any] | None

    # Описание почему выбран маршрут обновления памяти
    memory_route_reason: str | None

    # Специальное поле Guardrail
    k8s_guardrail_violation: dict[str, Any] | None

    # Structured Kubernetes diagnostic result
    diagnostic_answer: dict[str, Any] | None

    # Structured RCA draft generated from diagnostic_answer
    incident_report: dict[str, Any] | None

    # Ошибка формирования RCA draft
    incident_report_error: dict[str, Any] | None

    #  Какой specialist agent обработал запрос
    active_agent: Annotated[str | None, keep_latest_value]

    # Supervisor execution plan, полный набор специалистов, необходимых для выполнения запроса.
    required_agents: list[SupervisorAgentName]

    # Краткое объяснение выбора нескольких специалистов
    supervisor_reason: str | None

    # Ошибка structured output или supervisor execution planning
    supervisor_error: dict[str, Any] | None

     # Runbook, релевантный текущему запросу
    relevant_runbook: dict[str, Any] | None

    # Ошибка поиска runbook
    runbook_error: dict[str, Any] | None

    # Parallel execution Send use Reducer
    completed_agents: Annotated[list[str], operator.add]

    # Normalized evidence collected from specialist agents
    incident_context: dict[str, Any] | None

    # Aggregation error
    aggregation_error: dict[str, Any] | None

    # Structured quality evaluation of IncidentContext
    rca_quality_check: dict[str, Any] | None

    # Evaluator structured-output/runtime error
    evaluator_error: dict[str, Any] | None

    # Number of data collection retries by evaluator (termination condition)
    evaluation_retry_count: int

    # Optional reason why another collection round is needed
    evaluation_feedback: str | None

    # Human-in-the-loop
    approval_required: bool | None

    # Результат решения человека
    approval_status: Literal[
        "pending",
        "approved",
        "rejected",
    ] | None

    # Необязательный комментарий человека
    approval_feedback: str | None



class DiagnosticAnswer(BaseModel):
    """
    Final structured answer for Kubernetes diagnostics.
    
    This schema is used only for final user-facing Kubernetes diagnostic responses.
    """

    model_config = ConfigDict(extra="forbid")

    cluster: str | None = Field(
        default=None,
        description=(            
            "Name of the Kubernetes cluster where the affected service "
            "is running and the diagnostic was performed."
        )
    )

    namespace: str | None = Field(
        default=None,
        description=(
            "Name of the namespace where the affected service "
            "is running and the diagnostic was performed."
        )
    )

    service: str | None = Field(
        default=None,
        description="Name of the Kubernetes service, workload or application being Kubernetes diagnosed."
    )

    symptom: str | None = Field(
        default=None,
        description="Observed problem, error, or symptom investigated during the Kubernetes diagnostic."
    )

    summary: str = Field(
        ...,                                                                             # значит обязательное поле и значение по default отсутствует
        description="Short summary of the Kubernetes diagnostic result."
    )

    # Что было обнаружено в Kubernetes
    evidence: list[str] = Field(
        default_factory=list,
        description="Concrete evidence observed From Kubernetes tool results ot conversation context."
    )

    likely_causes: list[str] = Field(
        default_factory=list,
        description="Most likely causes based only on available evidence."
    )

    recommended_commands: list[str] = Field(
        default_factory=list,
        description="Safe read-only kubectl commands the user can run manually."
    )

    next_actions: list[str] = Field(
        default_factory=list,
        description="Recommended next diagnostic or operational actions."
    )

    # Какой сохранённый контекст помог агенту выбрать параметры для tool_calls
    memory_sources: list[str] = Field(
        default_factory = list,
        description=(
            "Long-term Memory facts that were actually used while resolving Kuberneets parameters "
            "For example, default namespace abitained from a ClusterContext."
        )
    )

# total=False: чтобы не требовать все поля при вызове графа
class MemoryAgentState(MessagesState, total=False):
    """
    State contract for the reusable memory subgraph.

    The subgraph is responsible only for reading and writing
    profile, project and cluster long-term memories.
    """

    # Полная long-term memory пользователя
    memory_context: dict[str, Any]

    # Только память, релевантная текущему запросу
    relevant_memory_context: Annotated[dict[str, Any], operator.or_]

    # Диагностика memory retrieval
    memory_read_error: dict[str, Any] | None

    # Решение memory router
    memory_route: Literal[
        "profile_memory",
        "project_memory",
        "cluster_memory",
        "none"
    ] | None

    # Результат записи
    memory_updated: bool | None
    memory_update_error: dict[str, Any] | None

    # Нужен для retrieval-фильтрации.
    # При независимом вызове может отсутствовать.
    route: Literal[
        "kubernetes",
        "chat",
        "mcp",
        "memory",
        "incident_report",
        "routing_error",
    ] | None


    # Какой specialist agent обработал запрос
    active_agent: Annotated[str | None, keep_latest_value]

    # Описание почему выбран маршрут обновления памяти
    memory_route_reason: str | None

    # Parallel execution Send use Reducer
    completed_agents: Annotated[list[str], operator.add]




class MemoryRouteDecision(BaseModel):
    """
    Decision returned by the memory classifier.
    """

    model_config = ConfigDict(extra="forbid")

    route: Literal[ 
        "profile_memory",
        "project_memory",
        "cluster_memory",
        "none",
        ] = Field(
            description=( 
                "Long-term memory namespace that should be updated. "
                "Use none when the message does not explicitly contain "
                "stable profile, project, cluster information."
            )
    )

    reason: str = Field(
        ...,
        description="Short explanation of the memory routing decision.",
    )