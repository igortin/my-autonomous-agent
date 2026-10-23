# my-autonomous-agent

## Week 9 Lesson 5
Trajectory (action_history) - последовательность шагов агента при достижении цели. Агент может перепланировать (Repalnner) следующие шаги с учётом собственных предыдущих попыток в рамках текущей цели.


Trajectory должна сохраняться после перепланирования и помогать выбирать следующие действия.

История позволяет агенту учитывать:
- что уже проверено;
- какие данные получены;
- какие повторные проверки имеют смысл.

> При этом успешное действие на шаге не означает достижение цели.


#### Идея 
Мы сохраняем историю действий шагов и результатов. 
> Полная trajectory в дальнейшем может также включать версии планов и решения Verifier.

### Тест

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

Создай запрос 1:
```
Проверь, что у Deployment colvir-back-deployment
в namespace colvir-test кластера docker-desktop
количество готовых реплик не меньше текущего
желаемого количества из spec.replicas.
Ничего не изменяй.
```

