# OpenAI text → text
from langchain_openai import ChatOpenAI

from sre_agent.config import settings


model = ChatOpenAI(
    model=settings.openai_model,
    base_url=settings.openai_base_url,
    api_key=settings.openai_api_key,
    temperature=0,
)
