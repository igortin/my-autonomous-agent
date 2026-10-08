from typing import Literal, Any
from pydantic import BaseModel, Field, ConfigDict, model_validator
from langgraph.graph import MessagesState

# -------------------------
#  Схема контракт ЦЕЛИ 
# -------------------------
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


# -------------------------
#  Схема AgentAction (проверяемое НАМЕРЕНИЕ)
# -------------------------
class AgentAction(BaseModel):
    """
    Официальное намерение задействовать один оперативный инструмент.
    Здесь агент описывает, что собирается сделать.
    """
    model_config = ConfigDict(
        extra="forbid",                         # отклоняет неизвестные поля
        str_strip_whitespace=True,              # убирает пробелы по краям строк
    )

    action_id: str = Field(
        min_length=1,
        description="Identifier of this action within the execution plan.",
    )

    tool: str = Field(
        min_length=1,
        description="Exact tool name from the available action catalog.",
    )

    arguments: dict[str, Any] = Field(
        description="Explicit arguments for the selected tool.",
    )

    expected_result: str = Field(
        min_length=1,
        description=(
            "Expected information or effect of the action. "
            "This is an expectation, not an observed result."
        ),
    )

    risk_level: Literal["read", "low", "medium", "high"]

# -------------------------
#  Схема ActionObservation (Проверяемый факт выполнения)
# -------------------------
class ActionObservation(BaseModel):
    """
    Фактический результат попытки выполнить AgentAction.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    action_id: str = Field(
        min_length=1
    )
    
    # описывает выполнение действия 
    success: bool = Field(
        strict=True                 # включает строгую проверку, без преобразования строк и чисел.
    )

    result: dict[str, Any] | None

    error: str | None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ActionObservation":
        """
        Проверка на противоречивость значений в атрибутах
        """
        if self.success:
            if self.error is not None:
                raise ValueError(
                    "Successful observation must not contain an error"
                )

            if self.result is None:
                raise ValueError(
                    "Successful observation must contain a result"
                ) 
        else:
           if not self.error:
                raise ValueError(
                    "Failed observation must contain an error"
                )

        return self
 


# -------------------------
#  Схема PlanStep
# -------------------------
class PlanStep(BaseModel):

    model_config = ConfigDict(extra="forbid")

    # уникальный идентификатор шага
    id: str = Field(
        min_length=1
        )

    # описание шага
    description: str = Field(
        min_length=1
        )

    # назание агента
    agent: str = Field(
        min_length=1
        )

    # тип действия
    action_type: Literal[
        "read",
        "write", 
        "verify",
        ] = Field(
            description="Only read and verify actions are allowed."
    )

    # Намерение 
    action: AgentAction

    # список зависимостей step ID  
    depends_on: list[str] = Field(
        default_factory=list
        )


# -------------------------
#  Схема ExecutionPlan
# -------------------------
class ExecutionPlan(BaseModel):

    model_config = ConfigDict(extra="forbid")

    # список объектов шагов
    steps: list[PlanStep] = Field(min_length=1)

    # Decorator
    @model_validator(mode="after")
    def validate_dependencies(self) -> "ExecutionPlan":
        """
        staticmethod проверяет каждый шаг, 
        так как атрибут зависимость (depends_on) может ссылаться 
        только на уже существующий шаг.
        """
        # Создаем список step IDs
        ids = [step.id for step in self.steps]

        # Проверка дублирования ID в списке
        if len(ids) != len(set(ids)):
            raise ValueError("Plan step IDs must be unique")

        # Создаем список намерений - action IDs
        action_ids = [step.action.action_id for step in self.steps]
        
        # Определеям дублирование action IDs в плане
        if len(action_ids) != len(set(action_ids)):
            raise ValueError(
                "Action IDs must be unique within an execution plan"
            )

        # Контейнер для step IDs - тип данных множество 
        seen: set[str] = set()

        # Проверка step на указанние дублирования зависимостей
        for step in self.steps:
            if len(step.depends_on) != len(set(step.depends_on)):
                raise ValueError(
                    f"Duplicate dependencies in step {step.id}"
                )

            # Если пересекаются множества, то возращается пустое множество set()
            # что означает на этом step в атрибуте depends_on записан объект step, который уже ранее на предыдущей итерации был записан в контейнер seen, 
            # что означает корректную ссылку на существующий step, иначе ссылается на unavailable step
            unknown_or_forward = set(step.depends_on) - seen

            # Если НЕ пустое множество, то вызывется исключение 
            if unknown_or_forward:
                raise ValueError(
                    f"Step {step.id} depends on unavailable earlier steps: "
                    f"{sorted(unknown_or_forward)}\n"
                    f"current state seen: {seen}"   
                )

            # Добавляем step ID
            seen.add(step.id)



        # вощращаем Объект класса ExecutionPlan
        return self


# -------------------------
#  Схема контракт AvailableAgent 
# -------------------------
class AvailableAgent(BaseModel):
    """
    Схема Агента используемого в PlannerInput.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)

    description: str = Field(min_length=1)


# -------------------------
#  Схема AvailableAction 
# -------------------------
class AvailableAction(BaseModel):
    """
    Схема описания Action используемого в PlannerInput.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    requires_approval: bool = False

    # JSON Schema аргументов инструмента: planner берёт отсюда точные имена ключей для tool_args
    args_schema: dict[str, Any] = Field(
        default_factory=dict
    )

# -------------------------
#  Схема PlannerInput 
# -------------------------
class PlannerInput(BaseModel):
    """
    Входной Контракт ожидаемый в Planner Agent.
    """

    # Объект Цель со всеми атрибутами 
    goal: AgentGoal

    # словать данных из памяти (не должно быть результатом выполнения tools)
    environment_knowledge: dict[str, Any] = Field(
        default_factory=dict
    )

    # список возможных Агентов
    available_agents: list[AvailableAgent] = Field(
        min_length=1
    )

    # список возможных Action
    available_actions: list[AvailableAction] = Field(
        min_length=1
    )

# -------------------------
#  Схема Termination contract
# -------------------------
TerminationReason = Literal[
    "goal_reached",
    "max_iterations_reached",
    "unrecoverable_error",
    "human_escalation_required",
]


# -------------------------
#  Выходная схема Verifier
# -------------------------

class GoalVerification(BaseModel):
    """
    Решение о достижении цели на основании наблюдений.

    При создании объекта staticmethod валидирует значения атрибутов и отклонит в случае противоречия.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    # булевый признак достижения цели после выполнения шага
    goal_reached: bool = Field(strict=True)

    # список критериев что уже подтверждено
    satisfied_criteria: list[str] = Field(
        default_factory=list
    )

    # список критериев что ещё не подтверждено
    missing_criteria: list[str] = Field(
        default_factory=list
    )

    # список подтверждений
    evidence: list[str] = Field(
        default_factory=list
    )

    # список требующихся действий (еще не вызванных)
    remaining_work: list[str] = Field(
        default_factory=list,
    )

    # сохранение причины
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_decision(self) -> "GoalVerification":

        # Создаем переменную типа tuple кортеж (immutable object)
        fields = (
            self.satisfied_criteria,
            self.missing_criteria,
            self.evidence,
            self.remaining_work,
        )

        for items in fields:
            # Проверка в значениях атрибутов списков на элементы состоящими только из пробелов
            if any(not item.strip() for item in items):
                raise ValueError(
                    "Verification lists must not contain blank items."
                )

            # Проверка в значениях атрибутов списков на дубликаты
            if len(items) != len(set(items)):
                raise ValueError(
                    "Verification lists must not contain duplicates."
                )

        # Проверка на пересечение списков
        overlap = set(self.satisfied_criteria) & set(self.missing_criteria)
        if overlap:
            raise ValueError(
                "A criterion cannot be satisfied and missing at the same time."
            )
        
        # Проверка на разные противоречия 
        if self.goal_reached:
            if self.missing_criteria:
                raise ValueError(
                    "Reached goal must not have missing criteria."
                )
        
            if self.remaining_work:
                raise ValueError(
                    "Reached goal must not have remaining work."
                )
            
            if not self.evidence:
                raise ValueError(
                    "Reached goal must have evidence."
                )  
               
        return self

# ----------------------------------
# Входная схема Verifier
# ----------------------------------
class VerifierInput(BaseModel):
    
    """
    Данные на основании которых verifier принимаети решения.
    """
    model_config = ConfigDict(extra="forbid")

    goal: AgentGoal

    observations: list[ActionObservation] = Field(
        default_factory=list
    )

    # текущее состояние выполнения агента
    current_state: dict[str, Any] = Field(
        default_factory=list
    )


# ----------------------------------
#  Схема состояния Агента (основная)
# ----------------------------------

# total=False: чтобы не требовать все поля при вызове графа
class SREAgentState(MessagesState, total=False):
    """
    Explicit state schema for SRE/Kubernetes assistant.
    """

    # желаемое конечное состояние по схеме AgentGoal и критерии успеха.
    goal: dict[str, Any] | None

    # ошибка преобразования пользовательского запроса в схему AgentGoal.
    goal_interpreter_error: dict[str, Any] | None

    # данные по схеме PlannerInput.
    planner_input: dict[str, Any] | None

    # упорядоченные шаги достижения цели.
    execution_plan: dict[str, Any] | None

    # текущий ID шага который сейчас выполняется.
    current_step: str | None

    # диагностика планировщика
    planner_error: dict[str, Any] | None

    # количество полностью завершённых lifecycle итераций.
    iteration_count: int

    # предохранитель количества итераций lifecycle (runtime-копия AgentGoal.max_iterations).
    max_iterations: int

    # причина окончательного завершения lifecycle.
    termination_reason: TerminationReason | None

    # признак, что агент не должен продолжать без решения человека.
    human_escalation_required: bool

    # объяснение причины эскалации.
    human_escalation_reason: str | None

    # уже завершённые шаги
    completed_step_ids: list[str]

    # Результат Executor шага и сериализованный ActionObservation.
    pending_step_result: dict[str, Any] | None

    # Нормализованные результаты список по схеме ActionObservation.
    observations: list[dict[str, Any]]

    # последнее решение Verifier по схеме GoalVerification
    verification: dict[str, Any] | None

    # список из GoalVerification missing_criteria
    replan_feedback: list[str]

    # ошибка безопасного выполнения шага
    execution_error: dict[str, Any] | None
