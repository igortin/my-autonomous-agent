import asyncio
import json
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv


# Загружаем переменные до импорта модулей,
# которые создают Settings и LLM.
REPO_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(REPO_ROOT / ".env")


from langchain_core.messages import HumanMessage
from sre_agent.config import build_run_config
from sre_agent.graph import build_graph


REQUEST = """
Исследуй причину CrashLoopBackOff pod bbox-1
в namespace colvir-test кластера docker-desktop.

Для достижения информационной цели необходимо:
1. Получить текущее состояние pod и его контейнеров.
2. Получить последние доступные логи контейнера.
3. Получить Kubernetes events, относящиеся к этому pod.
4. Сформулировать вероятную причину, подтверждённую
   собранными данными, и указать ограничения вывода.

Используй только read-only инструменты.
Ничего не изменяй в Kubernetes.
Не выполняй команды внутри контейнеров.
Максимум 3 итерации lifecycle.
""".strip()


from sre_agent.model import model

print("LLM endpoint:", model.openai_api_base)
print("LLM model:", model.model_name)


def print_json(value):
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


async def main():
    graph = build_graph()

    config = build_run_config(
        user_id="igor",
        thread_id=f"manual-week8-day7-{uuid4()}",
        environment="dev",
    )

    # Это лимит шагов выполнения графа,
    # а не количество lifecycle iterations.
    config["recursion_limit"] = 100

    initial_state = {
        "messages": [
            HumanMessage(content=REQUEST),
        ],
    }

    final_state = None

    print("REQUEST:")
    print(REQUEST)

    async for mode, payload in graph.astream(
        initial_state,
        config=config,
        stream_mode=["updates", "values"],
    ):
        if mode == "updates":
            for node_name, update in payload.items():
                print(f"\n--- NODE: {node_name} ---")
                print_json(update)

        elif mode == "values":
            # values содержит полное актуальное состояние.
            final_state = payload

    if final_state is None:
        raise RuntimeError("Graph returned no state")

    print("\n=== FINAL RESULT ===")

    for field in (
        "goal",
        "execution_plan",
        "iteration_count",
        "max_iterations",
        "termination_reason",
        "verification",
        "completed_step_ids",
        "replan_feedback",
        "goal_interpreter_error",
        "planner_error",
        "execution_error",
    ):
        print(f"\n{field}:")
        print_json(final_state.get(field))

    observations = final_state.get("observations", [])

    print(f"\nObservations collected: {len(observations)}")

    for observation in observations:
        print_json(observation)


if __name__ == "__main__":
    asyncio.run(main())