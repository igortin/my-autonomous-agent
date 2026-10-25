# my-autonomous-agent

## Week 9 Lesson 5

Защита от превышения попыток вызова иснтрумента — политика остановки повторов по известному состоянию Deployment ресурса.     

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

