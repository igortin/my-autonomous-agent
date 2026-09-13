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
    openai_base_url: str
    langsmith_tracing: bool
    openai_api_key_embedding: str
    openai_model_embedding: str
    openai_base_url_embedding: str



def load_settings() -> Settings:
    return Settings(

        openai_api_key=require_env(
            "OPENAI_API_KEY"
        ),

        openai_model=os.getenv(
            "OPENAI_MODEL",
            "qwen3-14b"
        ),

        openai_base_url=os.getenv(
            "OPENAI_BASE_URL",
            "http://100.113.179.69:8080/v1"
        ),

        openai_api_key_embedding=require_env(
            "OPENAI_API_KEY_EMBEDDING"
        ),

        openai_model_embedding=os.getenv(
            "OPENAI_MODEL_EMBEDDING",
            "qwen3-embedding"        
        ),

        openai_base_url_embedding=os.getenv(
            "OPENAI_BASE_URL_EMBEDDING",
            "http://100.113.179.69:8081/v1"
        ),
        langsmith_tracing=(
            os.getenv(
                "LANGSMITH_TRACING",
                "false"
            ).lower()
            == "true"
        )
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