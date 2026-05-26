import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from forge_bot.bot_profile import load_active_bot_profile
from forge_bot.engine import NvidiaNimProvider
from forge_bot.engine import answer as engine_answer

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_NVIDIA_TESTS") != "1",
    reason="live NVIDIA tests are opt-in; set RUN_LIVE_NVIDIA_TESTS=1",
)


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
async def test_live_nvidia_engine_answers_from_resolved_nutrition_chunk() -> None:
    _nvidia_provider()
    profile = load_active_bot_profile("nutrition", "bot_profiles")

    answer = await engine_answer(
        "Juanca",
        "Hoy tengo crossfit, que como al mediodia?",
        profile=profile,
        request_id="live-nutrition-router-test",
    )

    normalized = answer.lower()
    assert "30g" in normalized or "140g" in normalized
    assert "360g" in normalized or "495g" in normalized
