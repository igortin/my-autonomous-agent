# my-autonomous-agent

## Week 9 Lesson 1
#### Goal - Создание контракта AgentAction

#### Распределение ответственности
| Вопрос                        | Кто отвечает                                           |
|-------------------------------|--------------------------------------------------------|
| AgentGoal                     | Какого результата нужно достичь?                       |
| PlanStep                      | Какой шаг выполнить и от каких шагов он зависит?       |
| AgentAction                   | Какой инструмент вызвать, с какими аргументами и зачем?|
| StepObservation               | Что фактически получилось при выполенении              |


#### Как будет устроен новый контракт AgentAction

`AgentAction` хранит намерение.

```
ExecutionPlan(
    steps=[
        PlanStep(
            id="inspect-pod",
            description="Inspect current pod state",
            agent="kubernetes",
            action_type="read",
            action=AgentAction(...),
            depends_on=[],
        )
    ]
)
```

#### Тест

Выполнить команду:
```
export OPENAI_API_KEY="sk-proj-..."; 
export OPENAI_MODEL="gpt-5-mini"; 
export LANGSMITH_TRACING=true; 
export OPENAI_BASE_URL="https://api.openai.com/v1"
```

Запустить LangGraph server
```
langgraph dev
```

Создай запрос:
```
Определи причину, по которой pod bbox-1 в namespace colvir-test
кластера docker-desktop находится в CrashLoopBackOff.
Ничего не изменяй.
```