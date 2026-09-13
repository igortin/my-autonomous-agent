from langgraph.store.memory import InMemoryStore

from sre_agent.memory import (
    memory_value_to_text,
    extract_search_keywords,
    search_memories,
    build_memory_context,
    build_relevant_memory_context,
)




#######################################################
#  Тестируем функции memory_value_to_text() 
#######################################################

def test_memory_value_to_text_nested_structure():
    """
    котороая рекурсивно конвертиртацию структуры данных memory в searchable текст.
    """

    # Входнпя стурктура dict
    value = {
        "cluster": "bcloud-test",
        "namespaces": [
            "colvir-instance",
            "colvir-services",
        ],
        "metadata": {
            "environment": "test",
        },
    }

    # вызов функции
    result = memory_value_to_text(value)

    assert "bcloud-test" in result
    assert "colvir-instance" in result
    assert "colvir-services" in result
    assert "test" in result


def test_extract_search_keywords_normalizes_and_removes_duplicates():
    """
    Проверяем работу функции meextract_search_keywordsmory_value_to_text()
    Извлечение уникальных keywords (убираем дубликаты) из пользовательтского запроса.
    """    

    query = (
        "Проверь bcloud-test и BCloud-Test "
        "namespace colvir-instance"
    )

    result = extract_search_keywords(query)

    assert "bcloud-test" in result
    assert "colvir-instance" in result
    # duplicate должен исчезнуть
    assert result.count("bcloud-test") == 1


#######################################################
#  Тестируем фукнкции build_memory_context()
#######################################################

def test_build_memory_context_returns_user_scoped_memory():
    """
    и Persistant memory
    """
    store = InMemoryStore()

    user_id = "igor"

    # Записываем в Persistant memory
    store.put(
        ("profile", user_id),
        "profile",
        {
            "name": "Igor",
            "role": "SRE",
        },
    )
    # Записываем в Persistant memory
    store.put(
        ("projects", user_id),
        "bcloud",
        {
            "name": "B-Cloud",
            "environment": "production",
        },
    )
    # Записываем в Persistant memory
    store.put(
        ("clusters", user_id),
        "bcloud-test",
        {
            "cluster_name": "bcloud-test",
            "default_namespace": "colvir-instance",
        },
    )

    #  Читает Persistant memory и возращает dict
    context = build_memory_context(
        store=store,
        user_id=user_id,
    )

    assert context["profile"]["name"] == "Igor"
    assert context["projects"][0]["name"] == "B-Cloud"
    assert len(context["clusters"]) == 1
    assert (
        context["clusters"][0]["default_namespace"]
        == "colvir-instance"
    )

#######################################################
#  Тестируем фукнкции build_memory_context()
#######################################################

def test_memory_isolation_between_users():
    """
    Memory одного пользователя не должна попасть другому.
    """
    store = InMemoryStore()

    # Пользователь 1
    store.put(
        ("clusters", "igor"),
        "cluster-1",
        {
            "cluster_name": "cluster-igor",
        },
    )

    # Пользователь 2
    store.put(
        ("clusters", "alice"),
        "cluster-2",
        {
            "cluster_name": "cluster-alice",
        },
    )

    context = build_memory_context(
        store=store,
        user_id="igor",
    )

    assert len(context["clusters"]) == 1
    assert context["clusters"][0]["cluster_name"] == "cluster-igor"




#######################################################
#  Тестируем фукнкции search_memories()
#######################################################

def test_search_memories_finds_cluster_by_keyword():
    """
    Поиск в persistant memory по keywords
    """
    store = InMemoryStore()

    store.put(
        ("clusters", "igor"),
        "bcloud-k8s-colvir-test-csko-1",
        {
            "cluster_name":
                "bcloud-k8s-colvir-test-csko-1",
            "environment": "test",
            "default_namespace":
                "colvir-instance",
        },
    )

    results = search_memories(
            query=(
                "Покажи cluster "
                "bcloud-k8s-colvir-test-csko-1"
            ),
            user_id="igor",
            store=store,
        )

    assert len(results) == 1

    result = results[0]

    assert result["memory_type"] == "clusters"

    assert (
        result["value"]["cluster_name"]
        == "bcloud-k8s-colvir-test-csko-1"
    )

#######################################################
#  Тестируем фукнкции search_memories()
#######################################################

def test_search_memories_returns_empty_for_irrelevant_query():
    """
    Поиск в persistant memory по keywords которых нет
    """

    store = InMemoryStore()

    store.put(
        ("clusters", "igor"),
        "production",
        {
            "cluster_name": "production-cluster",
        },
    )

    results = search_memories(
        query="completely unrelated value",
        user_id="igor",
        store=store,
    )

    assert results == []





#######################################################
#  Тестируем фукнкции build_relevant_memory_context()
#######################################################
def test_relevant_memory_context_filters_clusters():
    """
        Retrieval должен возвращать релевантную память.
    """

    store = InMemoryStore()

    store.put(
        ("clusters", "igor"),
        "cluster-a",
        {
            "cluster_name": "bcloud-test",
            "default_namespace": "colvir-instance",
        },
    )

    store.put(
        ("clusters", "igor"),
        "cluster-b",
        {
            "cluster_name": "payments-prod",
            "default_namespace": "payments",
        },
    )

    context = build_relevant_memory_context(
        store=store,
        user_id="igor",
        user_text="Покажи bcloud-test",
        route="memory",
    )

    assert len(context["clusters"]) == 1

    assert context["clusters"][0]["cluster_name"] == "bcloud-test"

