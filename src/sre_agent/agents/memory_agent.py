from typing import Literal, Optional, Any, Annotated

from datetime import datetime

from trustcall import create_extractor

from pydantic import BaseModel, Field, ConfigDict, model_validator

from langchain_core.runnables import RunnableConfig

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

from langgraph.graph import StateGraph, MessagesState, END, START

# Across THREAD Memory
from langgraph.store.base import BaseStore

from textwrap import dedent

import json, re

from sre_agent.state import SREAgentState, MemoryAgentState, MemoryRouteDecision

from sre_agent.model import model

from sre_agent.memory import build_memory_context, relevant_memory_read_node
from sre_agent.utils import get_latest_human_message


#####################################################
## Memory classes
#####################################################

# Определение Pydentic класса Profile и его schema
class ProfileMemory(BaseModel):
    """
    Stable information about the user.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(description="The user's name", default=None)
    
    role: Optional[str] = Field(description="The user's professional role", default=None)
    
    job: Optional[str] = Field(description="The user's current job or specialization.", default=None)
    
    preferences: list[str] = Field(
        description="Stable communication and working preferences.", 
        default_factory=list                                                                # каждый вызов list() создаёт новый, независимый пустой собственный список при создании инстанса Profile
    )


class ProjectMemory(BaseModel):
    """
    Context related to one user project.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        description="Stable project name."
    )

    description: Optional[str] = Field(
        default=None,
        description="Short description of the project.",
    )

    technologies: list[str] = Field(
        default_factory=list,
        description="Technologies used by the project.",
    )

    responsibilities: list[str] = Field(
        default_factory=list,
        description="User responsibilities in the project.",
    )

    current_goals: list[str] = Field(
        default_factory=list,
        description="Current project goals.",
    )

    important_context: list[str] = Field(
        default_factory=list,
        description="Important stable project facts.",
    )



class ClusterContext(BaseModel):
    """
    Stable application-level context about one Kubernetes cluster.

    This model stores logical infrastructure knowledge.
    It must never contain credentials tokens, certificates, private keys or kubeconfig contents here.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        description=(
            "Exact Kubernetes cluster identifier explicitly stated by the user. "
            "Example: docker-desktop-test or bcloud-common-test."
        ),
    )

    environment: Literal["dev", "qa", "prod", "test"] = Field(
        ...,                                                                    # обязательное поле при создании объекта, создается @classmethod infer_environment_from_cluster_name()
        description="Logical cluster environment.",
    )
    
    default_namespace: str | None = Field(
        default=None,
        description=(
            "Default Kubernetes namespace used for this cluster. "
            "Use None when it is unknown."
        ),
    )

    owner_team: str | None = Field(
        default=None,
        description=(
            "Team responsible for the cluster. "
            "Use None when the owner is unknown."
        ),
    )
    
    common_services: list[str] = Field(
        default_factory=list,
        description=(
            "Stable list of common services deployed or frequently "
            "used in the cluster."
        ),
    )


    """
    Функция определяет значение аттрибута environment будущего объекта на основе cluster_name и затем создает объект класса ClusterContext.

    Декораторы применяются снизу вверх.
    Сначало -> @classmethod -  поскольку функция запускается ещё до создания объекта поэтому - @classmethod.
    Потом -> @model_validator - перед стандартной валидацией полей передай исходные данные в эту функцию.

    В дальнейшем при создании Exctractor-ом объекта:
    - автоматически находится функция помеченная @model_validator декоратором, которая записывает значение в аттрибут "environment".
    - выполняется стандартная валидация аттрибута - environment: Literal["dev", "qa", "prod", "test"].
    - создается объекта класса ClusterContext.
    """
    
    @model_validator(mode="before")
    @classmethod
    def infer_environment_from_cluster_name(
        cls,                # указание на себя же на класс
        value: Any          # значение передал Exctrator Trustcall на вход
    ) -> Any:
    
        """
        Функция определяет значение аттрибута environment будущего объекта на основе cluster_name.

        Example:
        bcloud-common-test -> test
        bcloud-platform-prod -> prod
        """
        
        # Проверяем входное значение является dict
        if not isinstance(value, dict):
            raise ValueError("Expected dictionary")

        # validator не мутирует данные вызывающего кода. Поэтому делаем копию dict.
        data = dict(value)

        # Пытаемся прочитать из dict значение ключа environment 
        if data.get("environment"):
            return data

        # Читаем из dict значения ключа name
        cluster_name = str(data.get("name", "")).strip().lower()
        

        """
        Поиск первого места в строке, соответствующее регулярному выражению:
        (?:^|[-_.]) 
            - где "?" - логического объединения 
            ^ - начало строки 
            [-_.] - один из разделителей - "_", ".", ","

        (dev|qa|prod|test) 
            - одно из значений

        (?:$|[-_.])
         - где "?" - логического объединения 
         -  $ - конец строки
         - [-_.] - один из разделителей - "_", ".", ","

        Пример поиска:  
        [-_.]prod[-_.]
        """

        # Поиск значения через regexp в raw string (r"...")
        environment_match = re.search(
            r"(?:^|[-_.])(dev|qa|prod|test)(?:$|[-_.])",
            cluster_name,
        )

        if environment_match:
            # Получаем первую группу в совпадении
            data["environment"] = environment_match.group(1)

        # Возращаем измененную копию dict с значением environment c целью валидации и дальнейшего создания объекта 
        return data




#####################################################
## Константы Long-term memory
#####################################################
MEMORY_SCHEMAS: dict[str, type[BaseModel]] = {
    "profile": ProfileMemory,
    "projects": ProjectMemory,
    "clusters": ClusterContext,
}




# Mapping маршрута (Memory Router) на namespace в Store
MEMORY_ROUTE_TO_TYPE: dict[str, str] = {
    "profile_memory": "profile",
    "project_memory": "projects",
    "cluster_memory": "clusters",
}



#####################################################
## Memory Router SYSTEM PROMPT
#####################################################

MEMORY_ROUTER_SYSTEM_MESSAGE = """
You are a long-term memory classifier.

Your only responsibility is to determine whether the latest
HumanMessage explicitly requests creating or updating long-term memory.

Analyze only the latest HumanMessage.


Select exactly one route:

- profile_memory:
  Stable information about the user.

- project_memory:
  Stable information about a named project.

- cluster_memory:
  Stable information about a Kubernetes cluster.

Rules:
- Do not answer the user.
- Do not call tools.
- Do not store secrets.
- Select exactly one route.
- Provide a short reason.
"""


#####################################################
## Memory Router
#####################################################

# Инициализируем модель для создания объектов роутинг класса MemoryRouteDecision
memory_router_model = model.with_structured_output(MemoryRouteDecision)

async def memory_router_node(state: MemoryAgentState, config: RunnableConfig, store: BaseStore):
    """
    Classify the latest user message for an explicit memory update.
    """

    # Читаем заметки из state
    memory_context = state.get(
        "memory_context", 
        {
            "profile": None,
            "projects": [],
            "clusters": [],
        }
    )


    try:
        latest_user_message = get_latest_human_message(state["messages"])

        # Рендерим System Prompt
        system_message = MEMORY_ROUTER_SYSTEM_MESSAGE.format(
            memory_context=json.dumps(
                memory_context,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

        # Получаем объект класса SelectRouteMemory
        decision: MemoryRouteDecision = await memory_router_model.ainvoke(
            [
                SystemMessage(content=system_message),
                latest_user_message,
            ]
        )

        return  {
            "memory_route": decision.route,              # записываем none, profile_memory, cluster_memory, project_memory
            "memory_route_reason": decision.reason,
            "memory_updated": False,
            "memory_update_error": None,
            "active_agent": "memory_agent_subgraph",
        }
    
    # Ошибка memory router не должна полностью блокировать ответ. Отправляем в чат и т.п.   
    except Exception as exc:
        return {
            "memory_route": "none",
            "memory_route_reason": "Memory routing failed; continuing in read-only mode.",
            "memory_updated": False,
            "memory_update_error": {
                "type": "memory_router_error",
             "message": str(exc),
            },
            "active_agent": "memory_agent_subgraph",
        }




#####################################################
## Node update_long_term_memory_node
#####################################################

def update_long_term_memory_node(state: MemoryAgentState, config: RunnableConfig, store: BaseStore):
    """
    Node: update_long_term_memory_node

    Exctract and save memory into namespace selected by router
               
    Профайл JSON документ c именем Key в store
    {
         'namespace': ['profile', user_id],
         'key': '...',
         'value': schema Profile{}
         'created_at': '...',
         'updated_at': '...'
    }   
    """
    
    # Получить User ID из входного параметра config
    user_id = config["configurable"]["user_id"]


    try:
        # Читаем state.memory_route - none, profile_memory, cluster_memory, project_memory и т.д.
        memory_route = state.get("memory_route")

        """
        Создаем memory_type на основе dict MEMORY_ROUTE_TO_TYPE
            profile_memory -> profile
            cluster_memory -> clusters
            project_memory -> projects
        """
        memory_type = MEMORY_ROUTE_TO_TYPE.get(memory_route)

        if memory_type is None:
            return {
                "memory_updated": False,
                "memory_update_error": {
                    "memory_type": memory_type,
                    "type": "memory_update_error",
                    "message": f"Unsupported memory route: {memory_route!r}",
                },
            }


        # Определить namespace принадлежащее User ID
        namespace = (memory_type, user_id)
        
        """
        Определяем схему/класс заметки memory на основе раннее определенном memory_type

        profile -> ProfileMemory класс
        projects -> ProjectMemory класс
        clusters -> ClustersMemory класс
        """
        # Получить класс из dict MEMORY_SCHEMAS
        memory_schema = MEMORY_SCHEMAS[memory_type]


        # Получаем ИМЯ класса для использования в Exctractor
        tool_name = memory_schema.__name__


        """
        Подготавливаем Extractor Trustcall 
        """
        # Определение переменной для использвания в System Prompt для Extractor Trustcall 
        memory_specific_rules = ""

        if memory_type == "clusters":
            memory_specific_rules = """
Cluster memory rules:

1. Cluster identification
- ClusterContext.name MUST contain the exact Kubernetes cluster name
  explicitly stated in the latest user message.
- Copy the cluster name exactly as written by the user.
- Preserve letters, numbers, dots, underscores, and hyphens.
- Remove only surrounding quotes and trailing punctuation.
- Never use the Pydantic schema name, tool name, class name,
  or memory namespace as ClusterContext.name.
- The following values are always invalid cluster names:
  "ClusterContext", "clusters", "cluster", "Kubernetes".
- Do not invent or infer a cluster name when the user did not provide one.
- Do not replace the user's cluster name with the name of an existing
  memory unless they are an exact match.

2. Existing cluster memories
- Treat ClusterContext.name as the stable identifier of a cluster memory.
- Update an existing cluster memory only when its name exactly matches
  the cluster name in the latest user message.
- Do not update a cluster memory using a partial, fuzzy, or similar name.
- Never copy fields from one cluster into another cluster.
- Preserve existing fields that the user did not explicitly change.

3. Environment
- Set environment only when one of these exact tokens appears in the
  cluster name: dev, qa, prod, or test.
- Infer the environment from a complete cluster-name token separated
  by "-", "_", or ".".
- Examples:
  "docker-desktop-test" -> "test"
  "bcloud_common_prod" -> "prod"
  "platform.qa.cluster" -> "qa"
- Do not infer an environment from unrelated words in the message.
- Do not overwrite an existing environment unless the cluster name
  explicitly indicates another supported environment.

4. Default namespace
- Extract default_namespace only when the user explicitly associates
  a namespace with the same cluster.
- Store only the namespace name, without words such as "namespace",
  "namespace по умолчанию", or "default namespace".
- Remove surrounding quotes and trailing punctuation.
- Do not use a namespace belonging to another cluster.
- If the user does not provide a namespace, preserve the existing
  default_namespace.
- For a new cluster without an explicitly provided namespace,
  set default_namespace to null.

5. Owner team
- Extract owner_team only when the user explicitly associates a team
  with the same cluster.
- Do not infer an owner team from project names, service names,
  namespaces, or previous conversations.
- If owner_team is not provided for a new cluster, use null.
- Preserve the existing owner_team when the user does not change it.

6. Common services
- Extract common_services only when the user explicitly states that
  services commonly exist in or belong to the same cluster.
- Do not treat pods, namespaces, one-time diagnostic targets,
  or temporary workloads as common services.
- Do not invent service names.
- For a new cluster with no explicitly mentioned common services,
  use an empty list.
- Preserve existing common_services when the user does not change them.

7. Output requirements
- Return only facts supported by the latest user message or preserved
  from the exact matching existing cluster memory.
- Never place explanatory text into any ClusterContext field.
- Never use "ClusterContext" as a field value.
- ClusterContext.name must always be a real cluster identifier taken
  from the latest user message.

Extraction example:

Latest user message:
Remember that cluster docker-desktop-test uses colvir-test as its
default namespace.

Expected extracted object:
{
    "name": "docker-desktop-test",
    "environment": "test",
    "default_namespace": "colvir-test",
    "owner_team": null,
    "common_services": []
}

Incorrect extracted object:
{
    "name": "ClusterContext",
    "environment": "test",
    "default_namespace": "colvir-test",
    "owner_team": null,
    "common_services": []
}
"""

        elif memory_type == "profile":
            memory_specific_rules = """
Profile memory rules:

- Save only stable information about the user.
- Do not save project or cluster information.
- Do not infer role or preferences.
- Preserve existing profile fields unless the user
explicitly changes them.
"""

        elif memory_type == "projects":
            memory_specific_rules = """
Project memory rules:

- ProjectMemory.name is the stable document identifier.
- Do not create a project when its name is unknown.
- Store only stable project facts.
- Do not put cluster-specific information into project memory.
"""

        # Рендерим System Prompt для Extractor
        TRUSTCALL_INSTRUCTION = f"""
Reflect on the latest user message and update only {memory_type} memory.

Memory namespace:
{memory_type}

Important rules:

- Store only stable information.
- Do not store temporary conversational details.
- Do not store credentials, tokens, secrets, kubeconfig contents, private keys or authentication data.
- Update only the selected memory namespace.
- Preserve existing facts that were not explicitly changed.

{memory_specific_rules}

System Time: {datetime.now().isoformat()}
"""

        # Инициализация Extractor Trustcall 
        extractor = create_extractor(
            model,                                # указываем модель
            tools=[memory_schema],                # указываем класс, который Extractor использует для создания инстанса с заполненными атрибутами на основе updated_messages и .
            tool_choice=tool_name,                # указываем использование ИМЯ схемы/класса
            enable_inserts=True,                  # позволяет extractor создавать новые заметки
        )


        # Поиск memories заметок в хранилище
        existing_items = store.search(namespace)

        # Создаем list of tuples в сооствествии schema JSON документов
        existing_memories = (
            [
                (
                    item.key, 
                    tool_name ,
                    item.value
                ) 
                for item in existing_items
            ] 
            if existing_items 
            else None
        )

        """
        Передаем в Extractor только System Prompt и последнее HumanMessage с целью повторно не анализировать всю историию сообщений чтобы обновить все memories заметки. 
        """
        latest_user_message = get_latest_human_message(state["messages"])

        # Конкатинация System Prompt Trustcall и последнего HumanMessage
        updated_messages = [
            SystemMessage(content=TRUSTCALL_INSTRUCTION),
            latest_user_message,
        ]
        
        """
        Обновляем существующие заметки memories или создаем новые 

        Получаем в result
        ```python
            {
                messages: AIMessage                  - содержит информацию про tool calls сделанные Extcrator-ом
                responses: list(ClusterConext{})     - содержит список memories обновленных и новых заметок
                metadata: list({id: str})            - содержит информацию id_tool_call вызовов и json_doc_id (если обновили существующий JSON документ)
            }
        ```
        """

        # Вызываем Trustcall и LLM, получаем список dict c обновленными заметками, а также новые документы.
        result = extractor.invoke({
                "messages": updated_messages,   
                "existing": existing_memories,
                }
        )

        print("Existing memories:")
        for memory in existing_memories or []:
            print(memory)

        print("\nExtractor responses:")
        for response in result["responses"]:
            print(response.model_dump())

        print("\nExtractor metadata:")
        for metadata in result["response_metadata"]:
            print(metadata)

    
        """
        Сохраняем обновленные заметки в виде JSON документов
        """
        # Итерируемся обновленным заметкам в list of Tuples
        for response, response_metadata in zip(result["responses"], result["response_metadata"]):

            # Получаем Key обновленного документа  
            memory_key = response_metadata.get("json_doc_id")

            # Определяем имя key документа 
            if not memory_key:
                if memory_type == "profile":
                    memory_key = "profile"
                elif memory_type in {"projects", "clusters"}:
                    memory_key = response.name
                else:
                    raise ValueError(
                        f"Unsupported memory type: {memory_type}"
                    )

            store.put(
                namespace,
                str(memory_key),
                response.model_dump(mode="json")                                            # Сохраняем JSON представление объекта "answer"
            )


        # Возращаем обычный Python dict и LangGraph обновляет MemoryAgentState. 
        # Так исправляется проблема устаревшего memory_context после store.put, поскольку build_memory_context загружает заново все заметки из store.
        return {
            "memory_context": build_memory_context(store=store, user_id=user_id),               # повторно прочитать память и перезаписать новыми данными
            "memory_updated": True,
            "memory_update_error": None,
        }


    except Exception as exc:
        return {
            "memory_updated": False,
            "memory_update_error": {
                "type": "memory_update_error",
                "memory_type": memory_type,
                "message": str(exc),
            },
        }





#####################################################
## Node memory_response_node
#####################################################

async def memory_response_node(
    state: MemoryAgentState,
    config: RunnableConfig,
    store: BaseStore,
) -> dict[str, Any]:
    """
    Produce the final user-facing response for the memory branch.
    """

    memory_updated = state.get("memory_updated")

    memory_route = state.get("memory_route")

    memory_update_error = state.get("memory_update_error")

    relevant_memory_context = state.get("relevant_memory_context", {})

    # Рендерим System Prompt
    system_prompt = dedent(
        f"""You are a memory specialist.

        Memory route:
        {memory_route}

        Memory updated:
        {memory_updated}

        Memory update error:
        {json.dumps(
            memory_update_error,
            ensure_ascii=False,
            default=str,
        )}

        Relevant memory:
        {json.dumps(
            relevant_memory_context,
            ensure_ascii=False,
            indent=2,
            default=str,
        )}

        Answer the user's latest request briefly.
        Do not invent memories.
        If memory was updated, confirm what was saved.
        If the request was a read request, report only stored information.
        """
    ).strip()

    response = await model.ainvoke(
        [
            SystemMessage(content=system_prompt),
            *state["messages"],
        ]
    )

    return {
        "messages": [response],
        "active_agent": "memory_agent_subgraph",
        "completed_agents": ["memory"]
    }



#####################################################
## Node load_memory_context_node
#####################################################

def load_memory_context_node(state: MemoryAgentState, config: RunnableConfig, store: BaseStore):
    """
    Node: load_memory_context_node

    Load all user-scoped long-term memory namespaces.

    This node:
    - does not call the LLM;
    - does not update Store;
    - does not decide routing;
    - only loads memory into graph state.
    """
    
    # Получить User ID из входного параметра config
    user_id = config["configurable"]["user_id"]

    # Retrun dict and LangGraph overwrite field user_profile in MemoryAgentState.
    return {
        "memory_context": build_memory_context(
            store=store, 
            user_id=user_id
        ),
    }



#####################################################
## Condition Edge route_memory_operation
#####################################################

def route_memory_operation(state: MemoryAgentState) -> Literal["update_long_term_memory_node", "relevant_memory_read_node"]:
    """
    Decide whether the latest message contains an explicit
    long-term memory update.
    """

    memory_route = state.get("memory_route")

    if memory_route in {
        "profile_memory",
        "project_memory",
        "cluster_memory",
    }:
        return "update_long_term_memory_node"

    return "relevant_memory_read_node"


####################################################
## Построение memory_agent_subgraph.
#####################################################

def memory_agent_subgraph():

        # Создание Subgraph c explicit state schema
    memory_subgraph_builder = StateGraph(MemoryAgentState)

    memory_subgraph_builder.add_node("load_memory_context_node", load_memory_context_node)

    memory_subgraph_builder.add_node("memory_router_node", memory_router_node)

    memory_subgraph_builder.add_node("update_long_term_memory_node", update_long_term_memory_node)

    memory_subgraph_builder.add_node("relevant_memory_read_node", relevant_memory_read_node)

    # memory_subgraph_builder.add_node("memory_response_node", memory_response_node)


    memory_subgraph_builder.add_edge(START, "load_memory_context_node")

    memory_subgraph_builder.add_edge("load_memory_context_node", "memory_router_node")

    # Condition Edge
    memory_subgraph_builder.add_conditional_edges(
        "memory_router_node",
        route_memory_operation,
        {
            "update_long_term_memory_node": "update_long_term_memory_node",
            # "relevant_memory_read_node": "relevant_memory_read_node",
            "relevant_memory_read_node": END,

        },
    )

    # memory_subgraph_builder.add_edge("update_long_term_memory_node", "relevant_memory_read_node")

    # memory_subgraph_builder.add_edge("relevant_memory_read_node", "memory_response_node")

    memory_subgraph_builder.add_edge("update_long_term_memory_node", END)

    # memory_subgraph_builder.add_edge("memory_response_node", END)

    return memory_subgraph_builder.compile()


memory_agent_subgraph = memory_agent_subgraph()