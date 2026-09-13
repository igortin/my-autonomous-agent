import re
from typing import Any

from langchain_core.runnables import RunnableConfig

# Across THREAD Memory
from langgraph.store.base import BaseStore

from sre_agent.state import SREAgentState, MemoryAgentState
from sre_agent.utils import get_latest_human_message


# кортеж произвольной длины, все элементы которого являются str
MEMORY_SEARCH_TYPES: tuple[str, ...] = ("projects", "clusters")


def memory_value_to_text(value: Any) -> str:
    """
    Рекурсивно конвертирует структуры данных memory в searchable текст.

    Поддерживает:
    - dict;
    - list;
    - tuple;
    - set;
    - строки;
    - числа;
    - bool;
    - None.
    """

    if value is None:
        return ""

    # Проверяем values если список и тд
    if isinstance(value, dict):
        # Возращаем конкатинацию рекурсивно вызванной функции которая возращает item как str(value)
        return " ".join(
            memory_value_to_text(item)              # вызываем рекурсивной функцию и попадаем на следующий блок обработки isinstance(value, (list,tuple, set))
            for item in value.values()              # value.values() возращает list значения словаря из dict, по этому list можно итерироваться
        )

    # Проверяем values если список и тд
    if isinstance(value, (list, tuple, set)):
        # Возращаем конкатинацию рекурсивно вызванной функции которая возращает item как str(value)
        return " ".join(memory_value_to_text(item) for item in value)

    # Возращаем string
    return str(value)


def extract_search_keywords(query: str) -> list[str]:
    """
    Извлечение уникальных keywords (убираем дубликаты) из пользовательтского запроса.
    """
    # Нормализация пользоватльского query
    normalized_query = query.strip().casefold()

    # Проверяем "пустой запрос?"
    if not normalized_query:
        return []

    # Делаем поиск по паттерну и возращам list[str]

    # Ключевое слово:
    # 1. начинается с буквы, цифры или подчёркивания;
    # 2. может содержать части, разделённые "." или "-";
    # 3. не может заканчиваться точкой или дефисом.
    keywords = re.findall(
        r"\w+(?:[.-]\w+)*",
        normalized_query,
    )

    """
    Создаёт новый словарь:
    dict.fromkeys(keywords)
        ключи — элементы списка keywords,
        значения — None (по умолчанию).

    list(...)
    Берёт ключи этого словаря и превращает их обратно в список.
    Порядок сохранится таким, как первый раз элементы встретились в keywords
    """

    # Удаляем дубликаты, сохраняя исходный порядок в list[str].
    return list(dict.fromkeys(keywords))


def search_memories(
        query: str,
        user_id: str,
        *,
        store: BaseStore,
        limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Search project, cluster memories using simple keyword matching.

    Search scope:
    - ("projects", user_id)
    - ("clusters", user_id)

    Matching:
    - case-insensitive;
    - searches JSON document values;
    - searches the Store item key;
    - supports nested dicts and lists;
    - does not require embeddings.


    The function can be called in two ways:
    search_memories(query, user_id, store=store)
    """

    if not isinstance(query, str):
        raise TypeError("query must be a string")

    if not isinstance(user_id, str):
        raise ValueError("user_id must be a string")

    if not user_id.strip():
        raise ValueError("user_id must be a non-empty string")

    if limit <= 0:
        return []

    # Возращает list[keyword] из пользовательского prompt
    keywords = extract_search_keywords(query)

    if not keywords:
        return []

    normalized_query = query.strip().casefold()

    """
    Получаем данные из заметок memories хранимых в Store.
    """

    # Определяем контейнер для результатов
    results: list[dict[str, Any]] = []

    # Итерируемся по реестру (кортеж) projects, clusters
    for memory_type in MEMORY_SEARCH_TYPES:

        # Определяем простраство пользователя в store
        namespace = (memory_type, user_id)

        # Чтение всех заметок memories пользователя
        items = store.search(namespace)

        # Итерируемся по всем заметкам из простраство пользователя
        for item in items:

            """
            item - объект класса langgraph.store.base.SearchItem

            Пример:
            Item(
                namespace=['clusters', 'user-123'],
                key='bcloud-common-test',
                value={
                    'cluster_name': 'bcloud-common-test',
                    'environment': 'test',
                    'default_namespace': 'bcloud-common-test'
                },
                created_at='2026-07-26T08:30:00+00:00',
                updated_at='2026-07-26T08:30:00+00:00',
                score=None
            )

            Получаем данные из заметок memories хранимых в Store.
            """

            # Получаем dict из value
            memory_value = item.value

            # Ищем в заметке по key, так и по его всем значениям полей. После канкатинируем все в одну str.
            searchable_text = " ".join(
                [
                    str(item.key),                                      # Читаем ключи key из dict -> 'bcloud-common-test'
                    memory_value_to_text(memory_value),                 # конвертирует значения из dict в str
                ]
            ).casefold()

            """
            Ищем совпадения keywords в searchable_text
            """
            # Простой поиск вхождения keyword (из пользовательский prompt) в searchable_text и получаем list[str]
            matched_keywords = [
                keyword
                for keyword in keywords
                if keyword in searchable_text
            ]

            # Если нет вхождений, останавливаем выполение итерациии и переходим к следующему item
            if not matched_keywords:
                continue

            """
            Устанавливаем Score для каждой заметки документа
            """
            # Простой ranking: чем больше keywords совпало, тем выше результат.
            score = len(matched_keywords)

            # Дополнительный вес, если вся исходная фраза встречается в документе целиком.
            if normalized_query in searchable_text:
                score = score + 2

            """
            Добавляем dict в контейнер результатов
            """
            results.append(
                {
                    "memory_type": memory_type,
                    "key": item.key,
                    "matched_keywords": matched_keywords,
                    "score": score,
                    "value": memory_value,
                }
            )

        """
        Сортировка списка по убыванию по трем значениям score, memory_type и key
        """
        results.sort(
            key=lambda result: (-result["score"], result["memory_type"], str(result["key"]),)
        )

    # Выводим list[dict] по убыванию
    return results[:limit]


def build_relevant_memory_context(
        store: BaseStore,
        user_id: str,
        user_text: str,
        route: str | None,
) -> dict[str, Any]:
    """
    Build request-specific memory context using keyword retrieval.

    Policy:
    - profile is included only for chat;
    - projects and clusters are retrieved by keyword;
    - retrieval does not call an LLM;
    - retrieval does not update Store.
    """

    # Загружаем все заметки из store
    full_memory = build_memory_context(store=store, user_id=user_id)

    search_results = search_memories(query=user_text, user_id=user_id, store=store)

    # Получаем Profile
    relevant_profile = (
        full_memory["profile"]
        if route in ("chat", "memory")
        else None
    )

    # Определяем контенйеры для релеватных данных согласно пользовательского prompt
    relevant_projects: list[dict[str, Any]] = []
    relevant_clusters: list[dict[str, Any]] = []

    for result in search_results:

        memory_type = result["memory_type"]

        memory_value = result["value"]

        if memory_type == "projects":
            relevant_projects.append(memory_value)

        elif memory_type == "clusters":
            relevant_clusters.append(memory_value)

    # Profile полезен для персонализации обычного chat-ответа.
    return {
        "profile": relevant_profile,
        "projects": relevant_projects,
        "clusters": relevant_clusters,
    }


def build_memory_context(store: BaseStore, user_id: str) -> dict[str, Any]:
    """
    Build complete user-scoped long-term memory context.
    """
    # Читаем все JSON docs и получаем (namspace, key, value)
    profile_items = store.search(("profile", user_id))
    project_items = store.search(("projects", user_id))
    cluster_items = store.search(("clusters", user_id))

    if profile_items:
        profile = profile_items[0].value
    else:
        profile = None

    return {
        "profile": profile,
        "projects": [
            item.value for item in project_items
        ],
        "clusters": [
            item.value for item in cluster_items
        ],
    }


def relevant_memory_read_node(
    state: SREAgentState | MemoryAgentState,
    config: RunnableConfig,
    store: BaseStore,
) -> dict[str, Any]:
    """
    Read complete and request-relevant long-term memory.

    The node:
    - reads Store;
    - does not modify Store;
    - does not append messages;
    - returns normalized memory context.
    """

    try:
        user_id = config["configurable"]["user_id"]

        latest_user_message = get_latest_human_message(
            state["messages"]
        )

        user_text = (
            latest_user_message.content
            if isinstance(latest_user_message.content, str)
            else str(latest_user_message.content)
        )

        route = state.get("route") or "memory"

        memory_context = build_memory_context(
            store=store,
            user_id=user_id,
        )

        relevant_memory_context = build_relevant_memory_context(
            store=store,
            user_id=user_id,
            user_text=user_text,
            route=route,
        )

        return {
            "memory_context": memory_context,
            "relevant_memory_context": relevant_memory_context,
            "memory_read_error": None,
        }

    except Exception as exc:
        empty_context = {
            "profile": None,
            "projects": [],
            "clusters": [],
        }

        return {
            "memory_context": empty_context,
            "relevant_memory_context": empty_context.copy(),
            "memory_read_error": {
                "type": "memory_read_error",
                "message": str(exc),
            },
        }
