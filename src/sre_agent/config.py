import os
from dataclasses import dataclass
from langchain_core.runnables import RunnableConfig

def require_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set"
        )

    return value


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    langsmith_tracing: bool
    openai_base_url: str



def load_settings() -> Settings:
    return Settings(

        openai_api_key=require_env(
            "OPENAI_API_KEY"
        ),

        openai_model=os.getenv(
            "OPENAI_MODEL",
            "gpt-5-mini",
        ),
        langsmith_tracing=(
            os.getenv(
                "LANGSMITH_TRACING",
                "true"
            ).lower()
            == "true"
        ),
        openai_base_url=os.getenv(
            "OPENAI_BASE_URL",
            "https://api.openai.com/v1"
        ),        
    )


settings = load_settings()

def build_run_config(*, user_id: str, thread_id: str, environment: str = "dev",) -> RunnableConfig:
    return {
        "configurable": {
            "user_id": user_id,
            "thread_id": thread_id,
        },

        "metadata": {
            "user_id": user_id,
            "thread_id": thread_id,
            "environment": environment,
            "agent": "sre_agent",
        },

        "tags": [
            "sre-agent",
            environment,
        ],
    }