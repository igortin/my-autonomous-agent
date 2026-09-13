# OpenAI text → text
from langchain_openai import ChatOpenAI

# Embeddings от OpenAI text → vector
from langchain_openai import OpenAIEmbeddings

from sre_agent.config import settings

model = ChatOpenAI(
    model=settings.openai_model,
    base_url=settings.openai_base_url,
    api_key=settings.openai_api_key,
    temperature=0,
    # Отключаем extended thinking (<think> блок) у qwen3, чтобы каждый вызов
    # не тратил десятки секунд на скрытые reasoning-токены перед tool call/ответом.
    # extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)


model_embeddings = OpenAIEmbeddings(
    model=settings.openai_model_embedding,
    base_url=settings.openai_base_url_embedding,
    api_key=settings.openai_api_key_embedding
)