import pytest
import yaml

from sre_agent.tools.kubernetes import (
    KubernetesClusterConfig,
    load_kubernetes_clusters,
)

# декоратор, который запускает один тест несколько раз с разными значениями параметра.
@pytest.mark.parametrize(
    "context",                              # имя аргумента тестовой функции.
    [None, "", " ", 123, False],            # значения, которые pytest по очереди передаёт в context
)
def test_cluster_config_rejects_invalid_context(context):
    """
    Проверяем в классе KubernetesClusterConfig метод валидации __post_init__(self)

    match="context":
        регулярное выражение, которому должен соответствовать текст ошибки.
    """
    with pytest.raises(ValueError, match="context"):
        KubernetesClusterConfig(
            alias="test-cluster",
            context=context,
        )




def test_yaml_without_context_is_rejected(tmp_path):
    """
    Тест моделирует неправильную конфигурацию без указания context.

    tmp_path:
        встроенная фикстура pytest.

    match="test-cluster":
        регулярное выражение, которому должен соответствовать текст ошибки.
    """
    config_path = tmp_path / "clusters.yaml"
    config_path.write_text(
        yaml.safe_dump({
            "clusters": {
                "test-cluster": {
                    "default_namespace": "payments",
                },
            },
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="test-cluster"):
        load_kubernetes_clusters(str(config_path))



def test_yaml_preserves_explicit_context(tmp_path):
    """
    Тест корректной заргузки конфигурации кластера.
    """
    config_path = tmp_path / "clusters.yaml"
    config_path.write_text(
        yaml.safe_dump({
            "clusters": {
                "payments-test": {
                    "context": "admin@payments-test",
                },
            },
        }),
        encoding="utf-8",
    )

    clusters = load_kubernetes_clusters(str(config_path))

    assert clusters["payments-test"].context == "admin@payments-test"