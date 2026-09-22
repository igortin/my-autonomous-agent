# my-autonomous-agent

## Week 8 Lesson 4

#### Goal - Создание ограниченного Aвтономного Цикла

Количество уже завершённых проходов никогда не может превысить `AgentGoal.max_iterations`.

#### Cемантика счётчика
| Поле                           | Значение                                                |
|--------------------------------|---------------------------------------------------------|
| max_iterations                 | Максимально разрешённое количество проходов в AgentGoal |
| iteration_count                | Количество уже завершённых проходов loop                |
| termination_reason             | Причина, по которой lifecycle завершён                  |

Одна итерация:
```
supervisor
  → specialists
  → aggregate
  → evaluator
```

Поэтому увеличивать iteration_count нужно после evaluator, а не в supervisor_node.



#### Архитектура
```mermaid
flowchart TD
    START([START]) --> GI[goal_interpreter_node]
    GI --> PA[planner_agent_node]

    PA --> C1{route_after_planner}
    C1 -->|continue| IL[initialize_lifecycle_node]
    C1 -->|stop| UE[unrecoverable_error_node]

    IL --> SN[supervisor_node]

    SN --> C2{{dispatch_specialists<br/>Send fan-out, no mapping}}
    C2 -->|Send: kubernetes| K8S[kubernetes_agent_subgraph]
    C2 -->|Send: memory| MEM[memory_agent_subgraph]
    C2 -->|Send: runbook| RB[runbook_agent_node]
    C2 -->|Send: chat| CHAT[chat_agent_node]
    C2 -.->|raise/error → literal node name| SE[supervisor_error]

    SE --> END1([END])
    CHAT --> END2([END])

    K8S --> AGG[aggregate_findings_node]
    MEM --> AGG
    RB --> AGG

    AGG --> EV[evaluator_node]
    EV --> AI[advance_iteration_node]

    AI --> C3{route_autonomous_lifecycle}
    C3 -->|continue| PR[prepare_retry_node]
    C3 -->|goal_reached| GR[goal_reached_node]
    C3 -->|max_iterations_reached| MI[max_iterations_reached_node]
    C3 -->|unrecoverable_error| UE
    C3 -->|human_escalation_required| HE[human_escalation_node]

    PR --> SN

    GR --> FR[final_rca_node]
    MI --> END3([END])
    UE --> END4([END])
    HE --> END5([END])

    FR --> PIR[publish_incident_report_node]

    PIR --> C4{route_after_human_approval}
    C4 -->|approved| END6([END])
    C4 -->|rejected| AR[approval_rejected_node]

    AR --> END7([END])
```
#### Важные архитектурные Механизм 
| Механизм                       | Назначение                                     |
|--------------------------------|------------------------------------------------|
| max_iterations                 | Ограничение общей автономности                 |
| termination_reason             | Объяснение завершения lifecycle                |
| Human approval                 | Разрешение конкретного рискованного действия   |