import json
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)

from langchain_core.runnables import RunnableConfig

from typing import Any, Literal 

from sre_agent.agents.planner_agent import (
    READ_ONLY_AVAILABLE_ACTIONS,
    validate_read_only_plan,
)

from sre_agent.model import model
from sre_agent.state import (
    AgentGoal,
    ExecutionPlan,
    SREAgentState,
)

from sre_agent.state import ActionObservation

from uuid import uuid4

from sre_agent.autonomy.duplicate_guard import (
    MAX_DUPLICATE_ATTEMPTS,
    build_action_attempt,
    build_action_fingerprint,
    count_duplicate_attempts,
    get_environment_fingerprint,
)
from sre_agent.autonomy.executor import READ_ONLY_TOOL_REGISTRY

# Инициализация LLM c структуированным выводом по схеме ExecutionPlan
replanner_model = model.with_structured_output(
    ExecutionPlan,
    method="function_calling",
    strict=False,
)

from pydantic import ValidationError




REPLANNER_SYSTEM_PROMPT = """
You are the Replanner of a read-only autonomous SRE agent.

Create a revised ExecutionPlan using:
- the original AgentGoal;
- completed observations;
- missing success criteria;
- available read-only actions.

Rules:
1. Return only ExecutionPlan.
2. Plan only the missing diagnostic work.
3. Do not repeat a successfully completed step unless the observation
   explicitly shows that retrying is useful.
4. Every executable step must use action_type="read".
5. Never create write, verify, delete, patch, scale, restart, exec, create,
   apply or approval steps.
6. Do not invent resource names or environment facts.
7. Every dependency must refer to an earlier step in the new plan.
8. Every step must contain exactly one AgentAction in its action field.

Use:
- action.action_id: unique within the new plan;
- action.tool: exact tool name from available_actions;
- action.arguments: exact argument names from the tool's args_schema;
- action.expected_result: expected information from this inspection;
- action.risk_level: "read".

Never create analysis or verification steps without an operational tool.

Observations follow the ActionObservation contract:
- action_id;
- success;
- result;
- error;
- action.

Use successful results as observed environment facts.
Use failed observations to understand why evidence is missing.
Do not assume that a failed action returned the requested resource.
Do not repeat a failed action unless there is a justified reason.
Never interpret expected_result as evidence.

Use remaining_work as guidance for missing evidence.
It is not an executable plan.
Validate every proposed check against available_actions.

Action history:
You receive action_history containing executed attempts
from the current lifecycle.

Each record includes:
- action_id;
- action with tool, arguments and expected_result;
- success;
- result;
- error;
- observed_at.

Review action_history before choosing the next actions.

Use action.tool and action.arguments to identify what was tried.
Different action IDs do not necessarily mean different operations.

Use success, result and error to understand the outcome.
expected_result describes intent and is never evidence.

Do not repeat an identical failed action without a concrete reason.
A transient timeout may justify retrying.
An unchanged authorization error usually requires escalation
or another permitted diagnostic approach.

Historical observations describe past state.
They do not automatically prove the current state.

Repeating reads:
repeat_budget lists every tool call already made in this lifecycle.
repeats_left is how many more times the same tool with the same
arguments is allowed while the environment state stays the same.

- Repeat a read only if it is needed for a missing criterion
  and repeats_left is greater than 0.
- Repeat a read only if the resource state may have changed:
  for example restart_count, phase or event count differed between
  earlier results. If earlier results of the same call were identical,
  repeating it will not produce new evidence; choose another action.
- If repeats_left is 0, do not plan that call.

blocked_actions lists calls already rejected by the duplicate guard.
Never plan an action whose tool and arguments match a blocked action.
Repeating it will stop the investigation with human escalation.

Prefer a different permitted diagnostic action that can produce
new evidence for the missing criteria.
"""


#####################################
# Вспомогательная функция расчета остатка повторов для Replanner
#####################################
def build_repeat_budget(
    state: SREAgentState,
) -> list[dict[str, Any]]:
    """
    Для каждого уже выполненного вызова (tool и arguments) считает repeats_left,
    сколько раз его ещё можно повторить при текущем известном состоянии среды.
    Расчёт совпадает с проверкой duplicate guard в Executor.
    """

    # Получаем список Наблюдений
    action_history = state.get("action_history") or []

    # Получаем список попыток ActionAttempt
    attempts = state.get("action_attempts") or []

    seen: set[str] = set()



    # Контейнер хранения количества     
    budget: list[dict[str, Any]] = []

    # Итерируемся по списку Наблюдений
    for raw in action_history:

        # Валидируем и создаем обьект Наблюдение
        observation = ActionObservation.model_validate(raw)

        # Читаем Намерение AgentAction
        action = observation.action

        if action is None:
            # Пропускаем и переходим к следующему Наблюдению
            continue

        # Получаем из реестра нужный инструмент по имени инструмента
        tool = READ_ONLY_TOOL_REGISTRY.get(action.tool)

        if tool is None:
            # Пропускаем и переходим к следующему Наблюдению
            continue

        try:
            normalized_arguments = tool.args_schema.model_validate(action.arguments).model_dump(mode="json")

        except ValidationError:
            # Пропускаем и переходим к следующему Наблюдению
            continue

        # Создаем Отпечаток вызова инструмента на основе Намерение и нормализованных параметров
        action_fingerprint = build_action_fingerprint(action, normalized_arguments)

        # Проверка уникальности отпечатка вызова инструмента 
        if action_fingerprint in seen:
            # Пропускаем и переходим к следующему Наблюдению
            continue

        # Добавляем Отпечатка вызова инструмента
        seen.add(action_fingerprint)


        # Тот же кандидат поптыки ActionAttempt, которого построит Executor при повторе
        candidate = build_action_attempt(
            action=action,
            normalized_arguments=normalized_arguments,
            environment_fingerprint=get_environment_fingerprint(
                action=action,
                normalized_arguments=normalized_arguments,
                action_history=action_history,
                args_schema=tool.args_schema,
            ),
        )

        # Считаем количество дублированных попыток ActionAttempt
        used = count_duplicate_attempts(candidate=candidate, attempts=attempts)

        # Создаем список из структур описывающих доступное количество вызовов инструментов
        budget.append(
            {
                "tool": action.tool,
                "arguments": normalized_arguments,
                "repeats_left": max(0, MAX_DUPLICATE_ATTEMPTS - used),
            }
        )

    return budget



#####################################
# Replanner node
#####################################

async def replanner_node(
        state: SREAgentState,
        config: RunnableConfig,
) -> dict:
    """
    Replanner должен создать пересмотренный новый план c только дополнительными диагностическами шагами для новой итерации lifecycle.
    """

    try:    
        # Читаем цель из state
        raw_goal =  state.get("goal")
        
        # Валидируем цель и получаем объект класса AgentGoal
        goal = AgentGoal.model_validate(raw_goal)

        # Создание списка наблюдений сериализованных в JSON      
        observations = [
            ActionObservation.model_validate(item).model_dump(mode="json")
            for item in (state.get("observations") or [])
        ]

        # Создание списка наблюдений сериализованных в JSON  
        action_history = [
            ActionObservation.model_validate(item).model_dump(
                mode="json"
            )
            for item in (state.get("action_history") or [])
        ]        

        # Инициализируем новый пересмотренный план
        revised_execution_plan = await replanner_model.ainvoke(
            [
                SystemMessage(content=REPLANNER_SYSTEM_PROMPT),
                HumanMessage(
                    content=json.dumps(
                        {
                            # передаем цель
                            "goal": goal.model_dump(mode="json"),

                            # передаем предыдущий план из state
                            "previous_plan": state.get("execution_plan"),

                            # последовательность наблюдений для существующего Verifier
                            "observations": observations,
                            
                            # последовательность наблюдений попыток для дальнейшего планирования
                            "action_history": action_history,

                            # попытки действия, поменченные как заблокированные duplicate guard-ом на Executor
                            "blocked_actions": state.get("blocked_actions") or [],                            

                            # сколько раз ещё можно повторить каждый выполненный вызов
                            "repeat_budget": build_repeat_budget(state),

                            # передаем список missing_criteria заполненный на verifier_node из state
                            "missing_criteria": state.get("replan_feedback",[]),

                            # передаем список возможно нужных действий
                            "remaining_work": (state.get("verification") or {}).get("remaining_work", []),

                            # передаем list of dicts разрешенных действий 
                            "available_actions": [ 
                                action.model_dump(mode="json")
                                for action in READ_ONLY_AVAILABLE_ACTIONS
                            ]
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            ],
            config=config
        )

        # Валидация нового пересмотренного плана и создание объекта по схеме ExecutionPlan
        new_execution_plan = validate_read_only_plan(
            ExecutionPlan.model_validate(revised_execution_plan)
        )

        # Настраиваем уникальность action_id между execution_plan. 
        # Так два запроса статуса одного Pod будут иметь разные action_id, даже если относятся к одинаковому диагностическому действию.
        # Но не нужно менять step.id и depends_on: зависимости у тебя ссылаются на идентификаторы шагов.
        for step in new_execution_plan.steps:
            step.action.action_id = f"action-{uuid4().hex}"

        return {
            # записываем новый пересмотренный execution_plan
            "execution_plan": new_execution_plan.model_dump(mode="json"),

            # обнуляем для следующей интерации lifecycle
            "completed_step_ids": [],

            # обнуляем для следующей интерации lifecycle
            "current_step": None,

            # обнуляем для следующей интерации lifecycle        
            "planner_error": None,

            # обнуляем для следующей интерации lifecycle
            "duplicate_blocked": False,
        }

    except Exception as exc:
        return {
            "planner_error": {
                "type": "replanner_error",
                "message": str(exc),
            },
            "execution_plan": None,                 # Удаляем старый план созданный на planner_agent
        }

#####################################
# CE route_after_replanner
#####################################
def route_after_replanner(
    state: SREAgentState,
) -> Literal["continue", "stop"]:
    """
    Функция проверяет наличие нового пересмотренного плана и ошибок его генерации
    """
    if state.get("planner_error"):
        return "stop"

    if not state.get("execution_plan"):
        return "stop"

    # Продолжаем на executor_node
    return "continue"