import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from forge_bot.engine import NvidiaNimProvider
from forge_bot.nutrition.plan import load_nutrition_plan_file
from forge_bot.nutrition.router import resolve_meal_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_NVIDIA_TESTS") != "1",
    reason="live NVIDIA tests are opt-in; set RUN_LIVE_NVIDIA_TESTS=1",
)

NUTRITION_PROFILE_ROOT = Path("bot_profiles/nutrition")


def _nvidia_provider() -> tuple[NvidiaNimProvider, str]:
    load_dotenv(Path(".env"))
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    base_url = os.getenv("NVIDIA_BASE_URL", "").strip()
    model = os.getenv("NVIDIA_MODEL", "").strip()
    if not api_key or api_key == "<nvidia_api_key>":
        pytest.skip("NVIDIA_API_KEY is not configured")
    if not base_url:
        pytest.skip("NVIDIA_BASE_URL is not configured")
    if not model:
        pytest.skip("NVIDIA_MODEL is not configured")
    return (
        NvidiaNimProvider(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=60,
        ),
        model,
    )


@pytest.mark.asyncio
async def test_live_nvidia_chat_smoke() -> None:
    provider, model = _nvidia_provider()

    answer = await provider.chat(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "/no_think\nResponde solo con: prueba nvidia ok",
            },
            {"role": "user", "content": "ping"},
        ],
    )

    assert "nvidia" in answer.lower()
    assert "ok" in answer.lower()


@pytest.mark.asyncio
async def test_live_nvidia_answers_from_resolved_nutrition_chunk() -> None:
    provider, model = _nvidia_provider()
    plan = load_nutrition_plan_file(NUTRITION_PROFILE_ROOT, "demo_plan.json")
    resolution = resolve_meal_context(
        plan,
        "Hoy tengo crossfit, que como al mediodia?",
    )
    assert resolution.is_resolved
    assert resolution.meal_block_key == "comida_2"

    context = {
        "situation_key": resolution.situation_key,
        "moment_key": resolution.moment_key,
        "meal_block_key": resolution.meal_block_key,
        "supplementation": resolution.supplementation,
        "meal_block": resolution.meal_block,
    }
    answer = await provider.chat(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "/no_think\n"
                    "Eres un bot nutricionista. Responde en espanol usando solo "
                    "el bloque nutricional dado. No inventes cantidades. "
                    "Devuelve una respuesta breve y practica."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Mensaje original: Hoy tengo crossfit, que como al mediodia?\n"
                    "Contexto nutricional resuelto:\n"
                    f"{json.dumps(context, ensure_ascii=False)}"
                ),
            },
        ],
    )

    normalized = answer.lower()
    assert "30g" in normalized or "140g" in normalized
    assert "360g" in normalized or "495g" in normalized
