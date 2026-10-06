# my-autonomous-agent

## Week 9 Lesson 2

#### Идея

- LLM формирует предложение действия, 
- Runtime проверяет и выполняет его, 
- Observer сохранит то, что произошло на самом деле.


### Goal - Создание контракта ActionObservation

#### Распределение ответственности

| Вопрос                        | Кто отвечает                                           |
|-------------------------------|--------------------------------------------------------| 
| AgentGoal                     | Какого результата нужно достичь?                       | 
| PlanStep                      | Какой шаг выполнить и от каких шагов он зависит?       | 
| AgentAction                   | Какой инструмент вызвать, с какими аргументами и зачем?| 
| ActionObservation             | Что фактически полуучили при выполенении               |  


#### Как будет устроен новый контракт ActionObservation

> `ActionObservation` контракт который хранит что получили при выполнении инструмента.

| Поле                          | Описание                                               |
|-------------------------------|--------------------------------------------------------|
| action_id                     | Какое действие породило наблюдение.                    |
| success                       | Успешно ли выполнено действие.                         |
| result                        | Полученные данные.                                     |
| error                         | Почему действие завершилось неудачей.                  |  


```
ActionObservation(
    action_id="read-pod-status",
    success=True,
    result={
        "pod": {
            "status": {
                "phase": "Running",
            },
        },
    },
    error=None,
)
```
> Observer фиксирует результат действия, verifier проверяет цель.

#### Связь между AgentAction и ActionObservation
```
action.action_id == observation.action_id
```

#### Компоненты

| Вопрос                        | Кто отвечает                                                        |
|-------------------------------|---------------------------------------------------------------------| 
| Executor                      | Проверить action, вызвать tool, получить нормализованный результат. |
| Нормализатор адаптер          | Перевести ответ tool (ToolMessage) в ActionObservation.             | 
| Observer                      | Проверить связь с action и сохранить observation.                   | 
| Verifier                      | Проверить достижение цели.                                          |  
| Replanner                     | Запланировать недостающие проверки.                                 |                          



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