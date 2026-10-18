# my-autonomous-agent

## Week 9 Lesson 4
Проверять факты Python-кодом и не разрешать LLM переопределять результат.




Детерминированое правило PodReadyRule проверки для Python явно связано c:
- критерием успешности, котороый нужно достичь;
- ресурсом, который проверяем;


```
deterministic_rule_one_pod_ready= PodReadyRule(
    kind = "PodReady",
    criterion = "Pod 'bbox-1' in namespace 'colvir-test' on cluster 'docker-desktop' has status.conditions[type="Ready"].status == "True".",
    cluster_alias = "docker_desktop",
    namespace = "colvir-test",
    pod = "colvir-front-test"
)
```


#### Идея:
- LLM интерпретирует смысл: анализирует причины, сопоставляет логи и события, предлагает следующие проверки.
- Python проверяет формальные условия: сравнивает числа, проверяет состояния и принимает окончательное решение по таким критериям.

#### Правило
> Критерий, закреплённый за Python, вообще не передаётся LLM для оценки.
> Детерминированный код точно проверяет заданное условие. Он не исправляет неправильно выбранное условие.



#### Архитектура Verifier
```mermaid
flowchart TD
    A["VerifierInput"] --> B["Разделение критериев"]
    B --> C["Проверки Python"]
    B --> D["Оставшиеся критерии: LLM"]
    C --> E["Объединение результатов"]
    D --> E
    E --> F["Валидация GoalVerification"]
```

#### Где использовать LLM, а где Python


Для твоего автономного SRE-агента граница выглядит так:

| Задача                                            | Подход.                                               |
|---------------------------------------------------|-------------------------------------------------------|
| Понять запрос пользователя                        | LLM                                                   |
| Составить план                                    | LLM                                                   |
| Объяснить связь ошибок в логах и событиях         | LLM                                                   |
| Предложить следующую проверку                     | LLM                                                   |
| Проверить Ready == "True"                         | Python (evaluate_pod_ready)                           |
| Проверить ready_replicas >= 3                     | Python (evaluate_deployment_replicas_ready)           |
| Проверить namespace и кластер                     | Python (evaluate_pod_ready)                           |
| Проверить свежесть observation                    | Python (evaluate_pod_ready)                           |
| Проверить зависимости шагов                       | Python (evaluate_pod_ready)                           |
| Проверить лимит итераций                          | Python (route_after_verification)                     |
| Проверить, разрешён ли инструмент                 | Python (executor_node)                                |
| Решить, нужен ли approval по политике             | Python (route_after_verification)                     |
| Объединить результаты всех критериев              | Python (verify_goal)                                  |
 

> Если все критерии детерминированные, Verifier не вызывает LLM.

Можно ли однозначно описать входные данные, условие и ожидаемый результат?  
Если да — обычно это задача обычного кода Python.  
Если требуется интерпретация неоднозначной информации — полезна LLM.  




#### Для подключения проверки Deployment в следующем расширении потребуется
1. Инструмент чтения Deployment.
2. Регистрация в каталоге Planner и реестре Executor.
3. Контракт правила с ресурсом и целевым количеством.
4. Проверка актуальности observation.
5. Отдельные тесты.


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
Определи причину, по которой pod bbox-1 в namespace colvir-test
кластера docker-desktop находится в CrashLoopBackOff.
Ничего не изменяй.
```

Создай запрос 2:
```
Проверь, что Pod colvir-front-test в namespace colvir-test
кластера docker-desktop имеет condition Ready=True.
Ничего не изменяй.
```