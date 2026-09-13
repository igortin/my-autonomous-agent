from sre_agent.model import model_embeddings
from langchain_core.documents import Document

# Vectore Store
from langchain_core.vectorstores import InMemoryVectorStore

from typing import Any, Annotated
import operator
from langgraph.graph import MessagesState
from langchain_core.runnables import RunnableConfig


# Across THREAD Memory
from langgraph.store.base import BaseStore

from sre_agent.utils import get_latest_human_message




#############################################################
## Runbook Agent State
#############################################################

# total=False: чтобы не требовать все поля при вызове графа
class RunbookAgentState(MessagesState, total=False):
    """
    State contract for the reusable kubernetes subgraph.
    """
     # Runbook, релевантный текущему запросу
    relevant_runbook: dict[str, Any] | None

    # Ошибка поиска runbook
    runbook_error: dict[str, Any] | None

    # Parallel execution Send use Reducer
    completed_agents: Annotated[list[str], operator.add]



#############################################################
## RUNBOOKS Documents
#############################################################

RUNBOOK_DOCUMENTS = [
    Document(
        page_content="""
Runbook: CrashLoopBackOff. 
It describes the troubleshooting process to follow when a Kubernetes pod repeatedly starts, crashes, and is restarted by Kubernetes. 
The runbook covers common causes such as application startup failures, incorrect configuration, missing environment variables or secrets,
dependency connectivity problems, failed health checks, insufficient CPU or memory resources, permission issues, and application errors. 
It provides a structured approach for reviewing pod status and events, analyzing current and previous container logs, checking exit codes 
and restart counts, validating configuration and dependencies, inspecting resource limits and probes, and identifying the appropriate 
remediation steps.
""",
        metadata={
            "name": "CrashLoopBackOff",
            "steps": """
- Проверить статус pod и restart count.
- Получить текущие логи контейнера.
- Получить логи предыдущего контейнера через --previous.
- Проверить pod events.
- Проверить command, args и environment variables контейнера.
- Проверить ConfigMap и Secret dependencies.
- Проверить readiness/liveness/startup probes.
        - Определить причину завершения контейнера и exit code.
""",
            "source": "local_runbook_dictionary",
        },
    ),
    Document(
        page_content="""
Runbook: ImagePullBackOff. 
It describes the troubleshooting process to follow when a Kubernetes pod cannot pull its container image and therefore fails to start successfully. 
The runbook covers common causes such as incorrect image names or tags, unavailable or deleted images, container registry connectivity problems,
authentication failures, missing or invalid imagePullSecrets, TLS or certificate issues, DNS resolution problems, and registry rate limits.
It provides a structured approach for reviewing pod events, validating the image reference, testing registry access, checking credentials and secrets, 
verifying network connectivity, and identifying the appropriate remediation steps.            
""",
        metadata={
            "name": "ImagePullBackOff",
            "steps": """
- Проверить имя image и tag.
- Проверить pod events.
- Проверить доступность container registry.
- Проверить imagePullSecrets.
- Проверить права service account на imagePullSecret.
- Проверить наличие указанного image/tag в registry.
""",
            "source": "local_runbook_dictionary",
        },
    ),
    Document(
        page_content="""
Runbook: Pending. 
It describes the troubleshooting process to follow when a Kubernetes pod remains in the stuck state and cannot be scheduled or started successfully. 
The runbook covers common causes such as insufficient CPU or memory resources, node selector or affinity constraints,
taints and tolerations, unavailable PersistentVolumeClaims, scheduling restrictions, resource quotas, and other Kubernetes scheduler-related issues.
It provides a structured approach for identifying the root cause, checking pod events and scheduler messages, 
validating cluster resources and configuration, and determining the appropriate remediation steps.            
""",
        metadata={
            "name": "Pending",
            "steps": """
- Проверить pod events.
- Проверить состояние scheduler.
- Проверить requests CPU и memory.
- Проверить свободные ресурсы Kubernetes nodes.
- Проверить nodeSelector и node affinity.
- Проверить taints и tolerations.
- Проверить PVC/PV binding.
""",
            "source": "local_runbook_dictionary",
        },
    )
]


#############################################################
## Vector Store
#############################################################

runbook_vector_store = InMemoryVectorStore(
    embedding=model_embeddings
)

runbook_vector_store.add_documents(
    RUNBOOK_DOCUMENTS
)



#############################################################
## HELPERS RUNBOOKS
#############################################################

def find_relevant_runbooks(user_text: str,  k: int = 2,) -> list[Document]:
    """
    Функция Semantic retrieval позволяет возращает k документов из Vector Store
    схожих пользотельскому запросу.
    """

    # семантический поиск на основе векторов 
    documents = runbook_vector_store.similarity_search(query=user_text, k=k)

    return documents



#############################################################
## Node runbook_agent_node
#############################################################

async def runbook_agent_node(
    state: RunbookAgentState,
    config: RunnableConfig,
    store: BaseStore,
):
    """
    Specialist context agent for operational runbooks.

    Responsibility:
    - inspect the latest user request;
    - find a relevant local runbook;
    - put the retrieved runbook into graph state;
    - do not call Kubernetes tools;
    - do not update long-term memory;
    - do not perform diagnostics.
    """

    try:

        latest_user_message = get_latest_human_message(state["messages"])

        user_text = (
            latest_user_message.content
            if isinstance(latest_user_message.content, str)
            else str(latest_user_message.content)
        )

        documents = find_relevant_runbooks(user_text, k=1)

        # если runbook не найден, агент выполнился успешно
        if documents is None:
           return {
            "relevant_runbook": None,
            "runbook_error": None,
            "completed_agents": ["runbook"]
           }

        retrieved_runbooks = []

        for document in documents:
            retrieved_runbooks.append(
                {
                    "name": document.metadata["name"],
                    "steps": document.metadata["steps"],
                    "source": document.metadata["source"],
                }
            )


        return {
            "relevant_runbook": {
                "query": user_text,
                "results": retrieved_runbooks,
            },
            "runbook_error": None,
            "completed_agents": ["runbook"]
        }
    except Exception as exc:
        return {
            "relevant_runbook": None,
            "runbook_error": {
                "type": "runbook_lookup_error",
                "message": str(exc),
            },
            "completed_agents": ["runbook"]
        }