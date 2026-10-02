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
#  Схема AgentAction (намерение)
# -------------------------
class AgentAction(BaseModel):
    """
    Официальное намерение задействовать один оперативный инструмент.
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
#  Схема Результат шага
# -------------------------

class StepObservation(BaseModel):
    """
    Фактический результат выполненного шага
    """
    model_config = ConfigDict(extra="forbid")

    # идентификатор шага
    step_id: str = Field(min_length=1)

    # название инструмента
    tool_name: str = Field(min_length=1)

    # результат
    ok: bool

    # краткое описание результата выполненного шага
    summary: str = Field(min_length=1)

    # данные собранные на шаге
    data: dict[str, Any] = Field(default_factory=dict)

    # хранение ошибки выполнения шага
    error: str | None = None


# -------------------------
#  Схема проверки Goal
# -------------------------

class GoalVerification(BaseModel):
    """
    Оценка достаточности собранных наблюдений для достижения цели после выполнения нескольких шагов
    """
    model_config = ConfigDict(extra="forbid")

    # булевый признак достижения цели после выполнения шага
    goal_reached: bool

    # список критериев которые достигли указанных в goal.success_criteria
    satisfied_criteria: list[str] = Field(
        default_factory=list
    )

    # список критериев которые не достигли указанных в goal.success_criteria
    missing_criteria: list[str] = Field(
        default_factory=list
    )

    # список подтверждений
    evidence: list[str] = Field(
        default_factory=list
    )

    # сохранение причины
    reason: str = Field(min_length=1)

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

    # предохранитель итераций (runtime-копия AgentGoal.max_iterations).
    max_iterations: int

    # причина окончательного завершения lifecycle.
    termination_reason: TerminationReason | None

    # признак, что агент не должен продолжать без решения человека.
    human_escalation_required: bool

    # объяснение причины эскалации.
    human_escalation_reason: str | None

    # уже завершённые шаги
    completed_step_ids: list[str]

    # сырой результат Executor до обработки Observer
    pending_step_result: dict[str, Any] | None

    # список нормализованные факты прошлых шагов по схеме StepObservation
    observations: list[dict[str, Any]]

    # последнее решение Verifier по схеме GoalVerification
    verification: dict[str, Any] | None

    # список из GoalVerification missing_criteria
    replan_feedback: list[str]

    # ошибка безопасного выполнения шага
    execution_error: dict[str, Any] | None
