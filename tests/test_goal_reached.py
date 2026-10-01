from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from sre_agent.autonomy.lifecycle import goal_reached_node
from sre_agent.state import SREAgentState


def test_success_adds_answer_to_message_history():
    builder = StateGraph(SREAgentState)
    builder.add_node("finish", goal_reached_node)
    builder.add_edge(START, "finish")
    builder.add_edge("finish", END)
    graph = builder.compile()

    result = graph.invoke({
        "messages": [
            HumanMessage(content="Проверь состояние payment-api")
        ],
        "goal": {
            "description": "Определить состояние payment-api",
        },
        "verification": {
            "goal_reached": True,
            "reason": "Состояние подтверждено наблюдениями.",
            "satisfied_criteria": ["Состояние pod получено"],
            "evidence": ["payment-api-1: Ready=True"],
        },
        "observations": [{
            "step_id": "inspect-pod",
            "tool_name": "get_pod_tool",
            "ok": True,
            "summary": "Pod находится в состоянии Running.",
            "data": {},
            "error": None,
        }],
    })

    assert result["termination_reason"] == "goal_reached"
    assert len(result["messages"]) == 2
    assert isinstance(result["messages"][0], HumanMessage)

    answer = result["messages"][-1]
    assert isinstance(answer, AIMessage)
    assert "Ready=True" in answer.content
    assert "Running" in answer.content
    assert "get_pod_tool" in answer.content