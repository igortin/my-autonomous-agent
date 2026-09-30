# OpenAI text → text
from langchain_openai import ChatOpenAI

# Embeddings от OpenAI text → vector
from langchain_openai import OpenAIEmbeddings

from sre_agent.config import settings


# model = ChatOpenAI(model="gpt-4o", temperature=0)

model = ChatOpenAI(
    model=settings.openai_model,
    # base_url=settings.openai_base_url,
    api_key=settings.openai_api_key,
    temperature=0,
)