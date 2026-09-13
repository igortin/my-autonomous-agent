from langchain_core.messages import HumanMessage


def get_latest_human_message(messages: list) -> HumanMessage:
    """
    Return the latest HumanMessage from conversation history.

    Else raises ValueError: when no HumanMessage exists.
    """

    # Итерируемся с конца списка
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message

    raise ValueError("No HumanMessage in graph state.")
