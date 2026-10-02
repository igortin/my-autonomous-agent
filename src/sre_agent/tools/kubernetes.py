from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator

from typing import Literal, Optional

from kubernetes.client.exceptions import ApiException
from dataclasses import dataclass
import yaml, os
from pathlib import Path
from kubernetes import client, config as kube_config

###########################################################
## Pydentic класс KubernetesClusterConfig и его schema
###########################################################
@dataclass(frozen=True)
class KubernetesClusterConfig:
    """
    Конфигурация явно выбранного Kubernetes-кластера.

    @dataclass(frozen=True):
        поля которого нельзя изменять после создания объекта.

    alias:
        Logical cluster name visible to the LLM.

    context:
        Real context name from kubeconfig.

    kubeconfig_file:
        Optional kubeconfig file path.
        None means KUBECONFIG or ~/.kube/config will be used.

    default_namespace:
        Default namespace for this cluster.

    Метод built-in __post_init__ запускается после конструктора __init__ когда поля объекта уже заполнены
    и выполняет проверки значений или вычисления дополнительных полей.
    """

    alias: str
    context: str
    kubeconfig_file: Optional[str] = None
    default_namespace: str = "default"
    description: str = ""

    # Отсутствующий, пустой или некорректный context вызывает ошибку до создания Kubernetes-клиента.
    def __post_init__(self):
        if (not isinstance(self.context, str) or not self.context.strip()):
            raise ValueError(
                f"Cluster {self.alias!r}: "
                "'context' must be an explicit non-empty string "
                "in clusters.yaml"                
            )


###########################################################
## Pydentic класс KubernetesToolInput и его schema
###########################################################
class KubernetesToolInput(BaseModel):
    action: Literal[
        "list_pods",
        "get_pod",
        "get_pod_logs",
        "get_pod_events",
        "list_nodes",
        "get_node",
        "get_node_events"
    ] = Field(
        default="list_pods", 
        description="Kubernetes action to execute"
    )

    cluster_name: str = Field(
        ...,
        description=(
            "Logical Kubernetes cluster alias, for example "
            "'bcloud-k8s-colvir-test-csko-1'."
        ),
    )

    namespace: Optional[str] = Field(
        default=None,
        min_length=1,
        description=(
            "Explicit Kubernetes namespace. "
            "If omitted or null, use the selected cluster's "
            "default_namespace from clusters.yaml."
        ),
    )
    pod_name: Optional[str] = Field(default=None, description="pod_name in Kubernetes cluster")

    node_name: Optional[str] = Field(default=None, description="node_name in Kubernetes cluster")

    container_name: Optional[str] = Field(default=None, description="container_name in running Pod")

    tail_lines: Optional[int] = Field(default=10, ge=1, le=300, description="number of lines in Pod's log")

    # decoractor после парсинга всех полей проверить, что для pod/node операций переданы обязательные параметры.
    @model_validator(mode="after")
    def validate_required_fields(self):
        if self.action:
            if not self.cluster_name:
                raise ValueError("cluster_name is required")

        if self.action in {"get_pod", "get_pod_logs", "get_pod_events"}:
            if not self.pod_name:
                raise ValueError("pod_name is required")
    
        if self.action in {"get_node", "get_node_events"}:
            if not self.node_name:
                raise ValueError("node_name is required")
    
        return self

###########################################################
## Класс UnknownKubernetesClusterError (ошибка выбора Kubernetes кластера)
###########################################################
class UnknownKubernetesClusterError(ValueError):
    """Raised when a cluster alias is not registered."""

###########################################################
## Helper функция Resolver кластера
###########################################################
def resolver_kubernetes_cluster(cluster_name: str) -> KubernetesClusterConfig:
    """
    Resolve a logical cluster alias to object KubernetesClusterConfig
    """

    normalized_name = cluster_name.strip().lower()

    cluster_config = KUBERNETES_CLUSTERS.get(normalized_name)

    if cluster_config is None:
        raise UnknownKubernetesClusterError(
            f"Unknown Kubernetes cluster: "
            f"{cluster_name!r}. "
            f"Available clusters: "
            f"{KUBERNETES_CLUSTERS}"
        )

    return cluster_config


###########################################################
## Helper функции для внутреннего вызова Kubernetes action
###########################################################

def create_kubernetes_core_v1_api(cluster_name: str) -> tuple[
    KubernetesClusterConfig,
    client.ApiClient,
    client.CoreV1Api,
]:
    """
    Create an isolated Kubernetes ApiClient for one explicitly selected cluster.
    """

    # Возращает объект класса KubernetesClusterConfig
    cluster_config = resolver_kubernetes_cluster(cluster_name)

    configuration = client.Configuration()

    kube_config.load_kube_config(
        config_file=cluster_config.kubeconfig_file,
        context=cluster_config.context,
        client_configuration=configuration,
        persist_config=False,
    )

    # Must be configured before ApiClient is created.
    configuration.verify_ssl = False

    print(
        f"Kubernetes cluster={cluster_config.alias}, "
        f"context={cluster_config.context}, "
        f"host={configuration.host}, "
        f"verify_ssl={configuration.verify_ssl}"
    )

    api_client = client.ApiClient(
        configuration=configuration,
    )

    try:
        # Возращает высокоуровневый типизированный Kubernetes клиент
        core_v1_api = client.CoreV1Api(
            api_client=api_client,
        )
    except BaseException:
        # Клиент ещё не передан вызывающей функции.
        # Освобождаем ресурс и повторно выбрасываем исключение.
        api_client.close()
        raise
    
    return (
        cluster_config,
        api_client,
        core_v1_api,
    )



def _run_kubernetes_action(action: str, cluster_name: str, **kwargs) -> dict:
    """
    Internal helper.

    Public LangChain tools call this helper.
    LLM should not see the generic action field.
    """


    # Создаем Объект класса KubernetesToolInput, путем вызова classmethod .model_validate() который верифицирует соотвествие входнго dict схеме класса.
    args = KubernetesToolInput.model_validate(
        {
            "action": action,
            "cluster_name": cluster_name,
            **kwargs,
        }
    )

    return _execute_kubernetes_api(args)

def _execute_kubernetes_api(args: KubernetesToolInput) -> dict:
    """
    Internal helper.

    Responsibility:
    - Execute Kubernetes API calls.
    - Return JSON-serializable dict.
    - Do not know anything about LangChain, LangGraph, messages, or tool calls.
    """
    # Инициализируем переменные 
    api_client = None
    result_metadata = {}

    try:
        # Инициалзируем KubernetesClusterConfig, Kubernetes API client, client
        cluster_config, api_client, v1 = create_kubernetes_core_v1_api(
            cluster_name=args.cluster_name
        )

        # Создаем метаданные для нормализации вывода
        result_metadata = {
            "cluster_name": cluster_config.alias,
            "cluster_context": cluster_config.context
        }

        # Определяем namespace
        namespace = (
            args.namespace
            if args.namespace is not None
            else cluster_config.default_namespace
        )

        # Реестр инстурментов для которых требуется namespace
        namespaced_actions = {
            "list_pods",
            "get_pod",
            "get_pod_logs",
            "get_pod_events",
        }

        # Проверяем namespace указан
        if args.action in namespaced_actions:
            if not isinstance(namespace, str) or not namespace.strip():
                raise ValueError(
                    f"Cluster {cluster_config.alias!r}: "
                    "namespace must be a non-empty string"
                )
            # добавляем namespace в метаданные
            result_metadata["namespace"] = namespace


        # Выполняем запрос
        if args.action == "list_pods":
            pods = v1.list_namespaced_pod(namespace=namespace)

            # Возращаем обычный Python dict
            return {
                "ok": True,
                **result_metadata,
                "action": args.action,
                "cluster_name": args.cluster_name,
                "namespace": namespace,
                "pods": [
                    {
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "phase": pod.status.phase,
                        "node": pod.spec.node_name,
                        "pod_ip": pod.status.pod_ip,
                        "restart_count": sum(
                            cs.restart_count
                            for cs in (pod.status.container_statuses or [])
                        ),
                    }
                    for pod in pods.items
                ],
            }

        if args.action == "get_pod":
            pod = v1.read_namespaced_pod(
                name=args.pod_name,
                namespace=namespace,
            )

            return {
                "ok": True,
                **result_metadata,
                "action": args.action,
                "pod": pod.to_dict(),
            }

        if args.action == "get_pod_logs":
            logs = v1.read_namespaced_pod_log(
                name=args.pod_name,
                namespace=namespace,
                container=args.container_name,
                tail_lines=args.tail_lines,
                timestamps=True,
            )

            return {
                "ok": True,
                **result_metadata,
                "action": args.action,
                "namespace": namespace,
                "pod_name": args.pod_name,
                "container_name": args.container_name,
                "logs": logs,
            }

        if args.action == "get_pod_events":
            events = v1.list_namespaced_event(
                namespace=namespace,
                field_selector=f"involvedObject.name={args.pod_name}",
            )

            return {
                "ok": True,
                **result_metadata,
                "action": args.action,
                "namespace": namespace,
                "pod_name": args.pod_name,
                "events": [
                    {
                        "type": event.type,
                        "reason": event.reason,
                        "message": event.message,
                        "count": event.count,
                        "first_timestamp": str(event.first_timestamp),
                        "last_timestamp": str(event.last_timestamp),
                    }
                    for event in events.items
                ],
            }

        if args.action == "list_nodes":
            nodes = v1.list_node()

            return {
                "ok": True,
                **result_metadata,
                "action": args.action,
                "nodes": [
                    {
                        "name": node.metadata.name,
                        "conditions": [
                            {
                                "type": condition.type,
                                "status": condition.status,
                                "reason": condition.reason,
                                "message": condition.message,
                            }
                            for condition in (node.status.conditions or [])
                        ],
                    }
                    for node in nodes.items
                ],
            }

        if args.action == "get_node":
            node = v1.read_node(name=args.node_name)

            return {
                "ok": True,
                **result_metadata,
                "action": args.action,
                "node": node.to_dict(),
            }

        if args.action == "get_node_events":
            events = v1.list_event_for_all_namespaces(
                field_selector=f"involvedObject.name={args.node_name}",
            )

            return {
                "ok": True,
                **result_metadata,
                "action": args.action,
                "node_name": args.node_name,
                "events": [
                    {
                        "namespace": event.metadata.namespace,
                        "type": event.type,
                        "reason": event.reason,
                        "message": event.message,
                        "count": event.count,
                        "first_timestamp": str(event.first_timestamp),
                        "last_timestamp": str(event.last_timestamp),
                    }
                    for event in events.items
                ],
            }

        return {
            "ok": False,
            **result_metadata,
            "error": f"Unsupported action: {args.action}",
        }

    except ApiException as e:
        return {
            "ok": False,
            **result_metadata,
            "error": "Kubernetes API error",
            "status": e.status,
            "reason": e.reason,
            "body": e.body,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
        }
    finally:
        if api_client is not None:
            api_client.close()


###########################################################
## Tool Schemas для специалиста `kubernetes_agent_subgraph`
###########################################################

class ListPodsToolInput(BaseModel):
    cluster_name: str = Field(
        ...,                                            # значит обязательное поле и значение по default отсутствует
        description=(
            "Logical Kubernetes cluster alias."
        )
    )
    
    namespace: Optional[str] = Field(
        default=None,
        min_length=1,
        description=(
            "Explicit Kubernetes namespace. "
            "If omitted or null, use the selected cluster's "
            "default_namespace from clusters.yaml."
        ),
    )


class GetPodToolInput(BaseModel):
    cluster_name: str = Field(
        ...,
        description=(
            "Logical Kubernetes cluster alias. "
        )
    )
    
    namespace: Optional[str] = Field(
        default=None,
        min_length=1,
        description=(
            "Explicit Kubernetes namespace. "
            "If omitted or null, use the selected cluster's "
            "default_namespace from clusters.yaml."
        ),
    )

    pod_name: str = Field(
        ...,                                            # значит обязательное поле и значение по default отсутствует
        description="Name of the Kubernetes pod."
    )


class GetPodLogsToolInput(BaseModel):
    cluster_name: str = Field(
        ...,
        description=(
            "Logical Kubernetes cluster alias. "
        )
    )

    namespace: Optional[str] = Field(
        default=None,
        min_length=1,
        description=(
            "Explicit Kubernetes namespace. "
            "If omitted or null, use the selected cluster's "
            "default_namespace from clusters.yaml."
        ),
    )

    pod_name: str = Field(
        ...,                                            # значит обязательное поле и значение по default отсутствует
        description="Name of the Kubernetes pod to get logs from."
    )

    container_name: Optional[str] = Field(
        default=None,
        description="Optional container name if the pod has multiple containers."
    )

    tail_lines: int = Field(
        default=10,
        ge=1,
        le=300,
        description="Number of recent lines to return."
    )


class GetPodEventsToolInput(BaseModel):
    cluster_name: str = Field(
        ...,
        description=(
            "Logical Kubernetes cluster alias. "
        )
    )

    namespace: Optional[str] = Field(
        default=None,
        min_length=1,
        description=(
            "Explicit Kubernetes namespace. "
            "If omitted or null, use the selected cluster's "
            "default_namespace from clusters.yaml."
        ),
    )

    pod_name: str = Field(
        ...,                                            # значит обязательное поле и значение по default отсутствует
        description="Name of the Kubernetes pod to get events from."
    )


class ListNodesToolInput(BaseModel):
    cluster_name: str = Field(
        ...,                                           # значит обязательное поле и значение по default отсутствует
        description=(
            "Logical Kubernetes cluster alias. "
        )
    )


class GetNodeToolInput(BaseModel):
    cluster_name: str = Field(
        ...,
        description=(
            "Logical Kubernetes cluster alias. "
        )
    )
    
    node_name: str = Field(
        ...,                             # значит node_name обязательное поле и значение по умолчанию отсутствует.
        description="Name of Kubernetes node."
    )


class GetNodeEventsToolInput(BaseModel):
    cluster_name: str = Field(
        ...,
        description=(
            "Logical Kubernetes cluster alias. "
        )
    )
    
    node_name: str = Field(
        ...,
        description="Name of the Kubernetes node to get events for."
    )


###########################################################
## LangChain Tools 
###########################################################

# LangChain использует docstring для описания инструмента Моделе

@tool(
    name_or_callable = "list_pods_tool",
    args_schema=ListPodsToolInput,
    return_direct=False
)
def list_pods_tool(
    cluster_name: str = None,
    namespace: Optional[str] = None,  
) -> dict:
    """
    List Kubernetes pods in a namespace.
    Use this tool when the user asks to show, list or inspects pods.
    """

    return _run_kubernetes_action(
        cluster_name = cluster_name,
        action="list_pods",
        namespace=namespace, 
    )


@tool(
    name_or_callable = "get_pod_tool",
    args_schema=GetPodToolInput,
    return_direct=False
)
def get_pod_tool(
    cluster_name: str = None,
    pod_name: str = None, 
    namespace: Optional[str] = None,
) -> dict:
    """
    Get detailed insformation about a specific Kubernetes pod in a namespace.
    Use this tool when the user asks about one exact pod.
    """

    return _run_kubernetes_action(
        cluster_name = cluster_name,
        action="get_pod",
        pod_name=pod_name,
        namespace=namespace,
    )


@tool(
    name_or_callable = "get_pod_logs_tool",
    args_schema=GetPodLogsToolInput,
    return_direct=False
)
def get_pod_logs_tool(
    cluster_name: str = None,
    pod_name: str = None, 
    namespace: Optional[str] = None,
    container_name: Optional[str] = None, 
    tail_lines: int = 10,
) -> dict:
    """
    Get logs from specific Kubernetes pod.
    Use this tool when the user asks for pod logs, appliaction logs or recent logs lines.
    """

    return _run_kubernetes_action(
        cluster_name = cluster_name,
        action="get_pod_logs",
        pod_name=pod_name,
        namespace=namespace,
        container_name=container_name,
        tail_lines = tail_lines,
    )

@tool(
    name_or_callable = "get_pod_events_tool",
    args_schema=GetPodEventsToolInput,
    return_direct=False
)
def get_pod_events_tool(
    cluster_name: str = None,
    pod_name: str = None, 
    namespace: Optional[str] = None,
) -> dict:
    """
    Get Kubernetes events related to a specific pod.
    Use this tool when the user asks why a pod failed, restarted, is pending, or has scheduling issues.
    """

    return _run_kubernetes_action(
        cluster_name = cluster_name,
        action="get_pod_events",
        pod_name=pod_name,
        namespace=namespace,
    )


@tool(
    name_or_callable = "list_nodes_tool",
    args_schema=ListNodesToolInput,
    return_direct=False
)
def list_nodes_tool(
    cluster_name: str = None,
) -> dict:
    """
    List Kubernetes cluster nodes.
    Use this tool when the user asks to show or list cluster nodes.
    """

    return _run_kubernetes_action(
        cluster_name = cluster_name,
        action="list_nodes",
    )


@tool(
    name_or_callable = "get_node_tool",
    args_schema=GetNodeToolInput,
    return_direct=False
)
def get_node_tool(
    cluster_name: str = None,
    node_name: str = None
    ) -> dict:
    """
    Get detailed information about a specific Kubernetes node.
    Use this tool when the user asks to show or list about one exact nodes.
    """

    return _run_kubernetes_action(
        cluster_name = cluster_name,
        action="get_node",
        node_name=node_name,
    )


@tool(
    name_or_callable = "get_node_events_tool",
    args_schema=GetNodeEventsToolInput,
    return_direct=False
)
def get_node_events_tool(
    cluster_name: str = None,
    node_name: str = None
    ) -> dict:
    """
    Get Kubernetes events related to a specific kubernetes node.
    Use this tool when the user asks about node problems, pressure, scheduling, readiness, or node-level events.
    """

    return _run_kubernetes_action(
        cluster_name = cluster_name,
        action="get_node_events",
        node_name=node_name,
    )

###########################################################
## HELPER load_kubernetes_clusters 
###########################################################

def load_kubernetes_clusters(config_path: str) -> dict[str, KubernetesClusterConfig]:
    """
    Read file specified in config_path and create cluster registry type dict[str, KubernetesClusterConfig].
    """

    with open(config_path, encoding="utf-8") as file:
        # возращает dict
        raw_yaml = yaml.safe_load(file)

    # Возращаем множество set объектов KubernetesClusterConfig
    return {
        alias: KubernetesClusterConfig(
            alias = alias,
            context = config.get("context"),
            kubeconfig_file = config.get("kubeconfig_file"),
            default_namespace = config.get("default_namespace", "default"),
            description = config.get("description", "")
        )
        for alias, config in raw_yaml["clusters"].items()
    }


def default_kubernetes_clusters_config_path() -> str:
    """
    Resolve clusters.yaml location independent of the process's current working
    directory (module-relative instead of cwd-relative "./config/clusters.yaml").

    Default location: <repo_root>/config/clusters.yaml, next to pyproject.toml.
    Override with the SRE_AGENT_CLUSTERS_CONFIG env var when needed.
    """

    override = os.environ.get("SRE_AGENT_CLUSTERS_CONFIG")

    if override:
        return override

    # src/sre_agent/tools/kubernetes.py -> repo root is 3 levels up
    repo_root = Path(__file__).resolve().parents[3]

    return str(repo_root / "config" / "clusters.yaml")


KUBERNETES_CLUSTERS = load_kubernetes_clusters(default_kubernetes_clusters_config_path())

