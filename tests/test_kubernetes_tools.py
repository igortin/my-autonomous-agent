from types import SimpleNamespace

from unittest.mock import MagicMock

import pytest

from sre_agent.tools import kubernetes as kubernetes_tools
from sre_agent.tools.kubernetes import (
    KubernetesClusterConfig,
    KubernetesToolInput,
    _execute_kubernetes_api,
)


 #######################################################
 # Тестируем валидацию входной модели KubernetesToolInput
 #######################################################

# Код внутри этого блока должен выбросить исключение ValueError» и это ожидаемое поведение, так как в классе KubernetesToolInput есть декораторе validate_required_fields требующий для action get_pod параметр pod_name
def test_get_pod_requires_pod_name():
    with pytest.raises(ValueError):
        KubernetesToolInput(
            action="get_pod",
            cluster_name="test-cluster",
            namespace="default",
        )

# Код внутри этого блока должен выбросить исключение ValueError» и это ожидаемое поведение, так как в классе KubernetesToolInput есть декораторе validate_required_fields требующий для action get_node параметр node_name
def test_get_node_requires_node_name():
    with pytest.raises(ValueError):
        KubernetesToolInput(
            action="get_node",
            cluster_name="test-cluster",
        )


 #######################################################
 # Создаем Fake Pod Kubernetes response
 #######################################################
def make_fake_pod(
    name: str,
    namespace: str = "default",
    phase: str = "Running",
    node_name: str = "worker-01",
    pod_ip: str = "10.0.0.10",
    restart_count: int = 0,
):
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            namespace=namespace,
        ),
        status=SimpleNamespace(
            phase=phase,
            pod_ip=pod_ip,
            container_statuses=[
                SimpleNamespace(
                    restart_count=restart_count
                )
            ],
        ),
        spec=SimpleNamespace(
            node_name=node_name,
        ),
    )



 #######################################################
 #  Тестируем вызов list_pods c mock
 #######################################################

# Параметр monkeypatch — встроенная fixture pytest. Она позволяет временно подменить функцию, переменную или объект. Мы подменяем create_kubernetes_core_v1_api() на fake. функцию.
def test_list_pods_without_real_cluster(monkeypatch):
    # имитирует реальный Kubernetes
    fake_v1 = MagicMock()
    # имитирует Kubernetes ApiClient.
    fake_api_client = MagicMock()

    #  ЕСЛИ мой код попросит список pod'ов, верни ему один pod payment-api-123 в состоянии Running с двумя рестартами».
    fake_v1.list_namespaced_pod.return_value=SimpleNamespace(
            items=[
                make_fake_pod(name="payment-api-123", namespace="colvir-instance", phase="Running", restart_count=2)
            ]
        )

    # Создаем конфигурацию 
    cluster_config = KubernetesClusterConfig(
        alias="bcloud-test",
        context="fake-context",
        kubeconfig_file="/fake/kubeconfig",
        default_namespace="colvir-instance",
    )

    """"
    Здесь подменяем функцию create_kubernetes_core_v1_api на 'lambda cluster_name: ...' для работы с MagicMock
    
    в тестируемой функции _execute_kubernetes_api

                TESTED
                   │
                   ▼
        _execute_kubernetes_api
                   │
                   ▼
        list_namespaced_pod()
                   │
                   ▼
               MagicMock
                   │
                   X
             Kubernetes
    """
    monkeypatch.setattr(
        kubernetes_tools,
        "create_kubernetes_core_v1_api",
        lambda cluster_name: (cluster_config, fake_api_client, fake_v1)
    )

    # Создаем Обьект KubernetesToolInput
    args = KubernetesToolInput(
        action="list_pods",
        cluster_name="bcloud-test",
        namespace="colvir-instance",
    )

    # Вызов тестируемой функции
    result = _execute_kubernetes_api(args)

    assert result["ok"] is True
    assert result["action"] == "list_pods"
    assert result["cluster_name"] == "bcloud-test"
    assert result["namespace"] == "colvir-instance"

    assert len(result["pods"]) == 1

    pod = result["pods"][0]

    assert pod["name"] == "payment-api-123"
    assert pod["phase"] == "Running"
    assert pod["restart_count"] == 2

    # проверяем что вызов был сделанв функции _execute_kubernetes_api верно:
    # наш tool должен был обратиться к Kubernetes API
    # ровно один раз
    # и запросить pod'ы именно в namespace colvir-instance иначе проверка не пройдет
    fake_v1.list_namespaced_pod.assert_called_once_with(namespace="colvir-instance")


 #######################################################
 #  Тестируем вызов get_pod_logs c mock
 #######################################################

# Параметр monkeypatch — встроенная fixture pytest. Она позволяет временно подменить функцию, переменную или объект. Мы подменяем create_kubernetes_core_v1_api() на fake. функцию.
def test_get_pod_logs_without_real_cluster(monkeypatch):

    # имитирует реальный Kubernetes
    fake_v1 = MagicMock()
    # имитирует Kubernetes ApiClient.
    fake_api_client = MagicMock()

    # ЕСЛИ мой код попросит список логи pod, верни ему записи.
    fake_v1.read_namespaced_pod_log.return_value = (
        "line-1\nline-2\nline-3"
    )

    # Создаем конфигурацию 
    cluster_config = KubernetesClusterConfig(
        alias="bcloud-test",
        context="fake-context",
        kubeconfig_file="/fake/kubeconfig",
        default_namespace="colvir-instance",
    )

    # Здесь подменяем функцию create_kubernetes_core_v1_api на 'lambda cluster_name: ...' для работы с MagicMock
    monkeypatch.setattr(
        kubernetes_tools,
        "create_kubernetes_core_v1_api",
        lambda cluster_name: (cluster_config, fake_api_client, fake_v1)
    )

   # Создаем Обьект KubernetesToolInput
    args = KubernetesToolInput(
        action="get_pod_logs",
        cluster_name="bcloud-test",
        namespace="colvir-instance",
        pod_name="payment-api",
        container_name="app",
        tail_lines=10,
    )

    # Вызов тестируемой функции
    result = _execute_kubernetes_api(args)

    assert result["ok"] is True
    assert result["logs"] == "line-1\nline-2\nline-3"

    # проверяем что вызов был сделанв функции _execute_kubernetes_api верно:
    # наш tool должен был обратиться к Kubernetes API
    # ровно один раз
    # и запросить pod'ы логи именно с указанными параметрами иначе проверка не пройдет
    fake_v1.read_namespaced_pod_log.assert_called_once_with(
        name="payment-api",
        namespace="colvir-instance",
        container="app",
        tail_lines=10,
        timestamps=True,
    )



 #######################################################
 #  Тестируем вызов get_pod c mock
 #######################################################

# Параметр monkeypatch — встроенная fixture pytest. Она позволяет временно подменить функцию, переменную или объект. Мы подменяем create_kubernetes_core_v1_api() на fake. функцию.
def test_get_pod_without_real_cluster(monkeypatch):

    # имитирует реальный Kubernetes
    fake_v1 = MagicMock()
    # имитирует Kubernetes ApiClient.
    fake_api_client = MagicMock()

    # cоздаётся фальшивый pod.
    fake_pod = MagicMock()

    fake_pod.to_dict.return_value = {
        "metadata": {
            "name": "payment-api"
        },
        "status": {
            "phase": "Running"
        },
    }

    # ЕСЛИ мой код спросит про под и вызовет fake_v1.read_namespaced_pod(), верни fake_pod
    fake_v1.read_namespaced_pod.return_value = fake_pod


    # Создаем конфигурацию 
    cluster_config = KubernetesClusterConfig(
        alias="bcloud-test",
        context="fake-context",
        kubeconfig_file="/fake/kubeconfig",
        default_namespace="colvir-instance",
    )

    # подмена настоящей функции create_kubernetes_core_v1_api на lambda cluster_name
    monkeypatch.setattr(
        kubernetes_tools,
        "create_kubernetes_core_v1_api",
        lambda cluster_name: (
            cluster_config,
            fake_api_client,
            fake_v1,
            ),
        )

    # Создаем вход для твоего Kubernetes tool. Определеям Обьект KubernetesToolInput
    args = KubernetesToolInput(
        action="get_pod",
        cluster_name="bcloud-test",
        namespace="colvir-instance",
        pod_name="payment-api",
    )

    # выполнение тестируемой функции и внктри вызывается read_namespaced_pod(), что возращает fake_pod данные
    result = _execute_kubernetes_api(args)

    assert result["ok"] is True

    assert result["pod"]["metadata"]["name"] == "payment-api"
    
    # проверяем что вызов был сделанв функции _execute_kubernetes_api верно:
    # наш tool должен был обратиться к Kubernetes API
    # ровно один раз
    # и запросил pod именно с указанными параметрами иначе проверка не пройдет
    fake_v1.read_namespaced_pod.assert_called_once_with(
        name="payment-api",
        namespace="colvir-instance",
    )


#######################################################
#  Тестируем вызов list_nodes c mock
#######################################################

# Параметр monkeypatch — встроенная fixture pytest. Она позволяет временно подменить функцию, переменную или объект. Мы подменяем create_kubernetes_core_v1_api() на fake. функцию.
def test_list_nodes_without_real_cluster(monkeypatch):

    # имитирует реальный Kubernetes
    fake_v1 = MagicMock()
    # имитирует Kubernetes ApiClient.
    fake_api_client = MagicMock()

    # cоздаётся фальшивая node.
    fake_node = SimpleNamespace(
        metadata=SimpleNamespace(
            name="worker-01"
        ),
        status=SimpleNamespace(
            conditions=[
                SimpleNamespace(
                    type="Ready",
                    status="True",
                    reason="KubeletReady",
                    message="kubelet is ready",
                )
            ]
        ),
    )

    # ЕСЛИ мой код спросит про ноды и вызовет fake_v1.list_node(), верни fake_node
    fake_v1.list_node.return_value = SimpleNamespace(items=[fake_node])


    # Создаем конфигурацию 
    cluster_config = KubernetesClusterConfig(
        alias="bcloud-test",
        context="fake-context",
    )

    # подмена настоящей функции create_kubernetes_core_v1_api на lambda cluster_name
    monkeypatch.setattr(
        kubernetes_tools,
        "create_kubernetes_core_v1_api",
        lambda cluster_name: (
            cluster_config,
            fake_api_client,
            fake_v1,
        ),
    )

    # Создаем вход для твоего Kubernetes tool. Определеям Обьект KubernetesToolInput
    args = KubernetesToolInput(
        action="list_nodes",
        cluster_name="bcloud-test",
    )

    # выполнение тестируемой функции и внктри вызывается list_node(), что возращает fake_node
    result = _execute_kubernetes_api(args)

    assert result["ok"] is True

    assert result["nodes"][0]["name"] == "worker-01"

    assert result["nodes"][0]["conditions"][0]["type"] == "Ready"


    