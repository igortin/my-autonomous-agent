from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

# Across THREAD Memory
from langgraph.store.base import BaseStore

from textwrap import dedent

import json

from sre_agent.state import SREAgentState
from sre_agent.model import model
from sre_agent.memory import build_relevant_memory_context
from sre_agent.utils import get_latest_human_message


#############################################################
## CHAT Agent SYSTEM PROMPT
#############################################################

CHAT_SYSTEM_PROMPT = """
You are the conversational specialist of a multi-agent SRE assistant.

You handle plain dialogue: greetings, small talk, general questions
that do not require live Kubernetes diagnostics, runbook lookup or
long-term memory updates.

Use the relevant long-term memory below only to personalize your
answer (for example, address the user by name or refer to a known
project or cluster). Do not invent facts that are not present there.

Do not perform Kubernetes diagnostics.
Do not search runbooks.
Do not claim to have updated long-term memory.

Relevant memory:
{relevant_memory_context}
"""


#############################################################
## Node chat_agent_node
#############################################################

def chat_agent_node(
    state: SREAgentState,
    config: RunnableConfig,
    store: BaseStore,
) -> dict[str, Any]:
    """
    Specialist node for plain conversational turns.

    Responsibility:
    - load request-relevant long-term memory for personalization;
    - answer the user directly;
    - do not call Kubernetes tools;
    - do not search runbooks;
    - do not update long-term memory.
    """

    user_id = config["configurable"]["user_id"]

    latest_user_message = get_latest_human_message(state["messages"])

    user_text = (
        latest_user_message.content
        if isinstance(latest_user_message.content, str)
        else str(latest_user_message.content)
    )

    relevant_memory_context = build_relevant_memory_context(
        store=store,
        user_id=user_id,
        user_text=user_text,
        route="chat",
    )

    system_prompt = dedent(
        CHAT_SYSTEM_PROMPT.format(
            relevant_memory_context=json.dumps(
                relevant_memory_context,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    ).strip()

    response = model.invoke(
        [
            SystemMessage(content=system_prompt),
            *state["messages"],
        ]
    )

    return {
        "messages": [response],
        "relevant_memory_context": relevant_memory_context,
        "active_agent": "chat_agent_node",
        "completed_agents": ["chat"],
    }
