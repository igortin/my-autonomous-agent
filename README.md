# my-autonomous-agent

## Week 8 Lesson 3



#### Goal   
Преобразует свободный запрос юзера в проверяемый контракт AgentGoal

Для запроса:
```
Восстанови payment-api до 3 реплик
```

граф должен получить примерно такой объект:
```
{
  "description": "Ensure payment-api has 3 ready replicas",
  "success_criteria": [
    "deployment/payment-api spec.replicas == 3",
    "deployment/payment-api status.readyReplicas == 3"
  ],
  "constraints": [
    "Do not modify unrelated workloads",
    "Require approval before write operations"
  ],
  "max_iterations": 5
}
```

#### Результат дня:
``` mermaid
flowchart TD
    A["User request"] --> B["goal_interpreter_node"]
    B --> C["AgentGoal in state"]
    C --> D["supervisor_node"]
    D --> E["Specialist agents"]
```

| Компонент                     | Ответственность                                       |
|-------------------------------|-------------------------------------------------------|
| Goal Interpreter              | Какое конечное состояние требуется?                   |
| Supervisor                    | Какие специалисты сейчас нужны?                       |
| Planner                       | Какие действия приведут к цели?                       |
| Evaluator                     | Достигнута ли цель?                                   |
| Termination policy            | Продолжать или завершить работу?                      |

#### Control Loop
- agents/ содержит специалистов;
- autonomy/ будет содержать control-loop автономного агента;
- Goal Interpreter — не Kubernetes-специалист;
- он является частью управляющего слоя автономности.


#### Распределение ответственности
| Компонент                     | Ответственность                                       |
|-------------------------------|-------------------------------------------------------|
| AgentGoal                     | Пользователь                                          |
| goal_interpreter_node         | Преобразование текста в AgentGoal                     |
| SREAgentState.goal            | Хранение цели между node                              |
| model.with_structured_output  | LLM вернет результат по схеме                         |