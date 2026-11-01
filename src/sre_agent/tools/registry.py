from sre_agent.tools.catalog import (
    ToolCategory,
    ToolDefinition,
)


from sre_agent.tools.kubernetes import (
    get_deployment_tool,
    get_node_events_tool,
    get_node_tool,
    get_pod_events_tool,
    get_pod_logs_tool,
    get_pod_tool,
    list_nodes_tool,
    list_pods_tool,
)


##############################################
# Реестр Инструментов
##############################################
TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "list_pods_tool": ToolDefinition(
        tool=list_pods_tool,
        category=ToolCategory.READ,
        description="List pods in a namespace.",
        agent = "kubernetes",
    ),
    "get_pod_tool": ToolDefinition(
        tool=get_pod_tool,
        category=ToolCategory.READ,
        description="Inspect one Kubernetes pod.",
        agent = "kubernetes",
    ),
    "get_pod_logs_tool": ToolDefinition(
        tool=get_pod_logs_tool,
        category=ToolCategory.READ,
        description="Read recent logs from one pod.",
        agent = "kubernetes",
    ),
    "get_pod_events_tool": ToolDefinition(
        tool=get_pod_events_tool,
        category=ToolCategory.READ,
        description="Read Kubernetes events related to one pod.",
        agent = "kubernetes",
    ),
    "list_nodes_tool": ToolDefinition(
        tool=list_nodes_tool,
        category=ToolCategory.READ,
        description="List Kubernetes nodes.",
        agent = "kubernetes",
    ),
    "get_node_tool": ToolDefinition(
        tool=get_node_tool,
        category=ToolCategory.READ,
        description="Inspect one Kubernetes node.",
        agent = "kubernetes",
    ),
    "get_node_events_tool": ToolDefinition(
        tool=get_node_events_tool,
        category=ToolCategory.READ,
        description="Read events related to one node.",
        agent = "kubernetes",
    ),
    "get_deployment_tool": ToolDefinition(
        tool=get_deployment_tool,
        category=ToolCategory.READ,
        description=(
            "Read one Deployment, including spec.replicas, "
            "status.ready_replicas, metadata.generation "
            "and status.observed_generation."
        ),
        agent = "kubernetes",
    ),
}